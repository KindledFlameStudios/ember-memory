# Ember Memory — Plan 5: First-Wave Product Hooks

> **For agentic workers:** Use this plan to implement the first
> user-facing product hooks that came out of the March 31 brainstorm.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the brainstorm synthesis into a concrete first-wave build
that sharpens `ember-memory` as a product, not just a technical memory
engine. The first wave should make the engine visible, create a strong
onboarding story around resurrected context, and polish the cross-AI
continuity claim enough to support release messaging.

**Product Threads:** `Visible Engine`, `Resurrection`, `Portable Brain`

**Build Order:**
1. Visible Engine
2. Resurrection
3. Portable Brain polish

**Why this order:** Visible Engine is the fastest path to trust and
shareable proof. Resurrection is the strongest onboarding hook.
Portable Brain already exists architecturally, but needs product polish
to feel like a clean promise.

**Depends on:** Plans 1-4, especially the Engine work and the current
multi-CLI architecture

**Spec:** `docs/superpowers/specs/2026-03-31-ember-memory-product-threads.md`

---

## Success Criteria for This Plan

By the end of this plan, `ember-memory` should be able to truthfully
show users:

- why a memory surfaced
- what the engine is currently "hot" around
- a compelling first-run path for importing old context
- a smoother story for moving memory across AI tools

This plan is intentionally focused. It is **not** the plan for team
memory, gamification, public gardens, or a full analytics suite.

---

## Task 1: Visible Engine Foundation

**Outcome:** Retrieval results can explain themselves. The controller can
show the engine's current state in a way that builds trust.

**Files:**
- Update: `ember_memory/core/search.py`
- Update: `ember_memory/core/engine/state.py`
- Update: `ember_memory/core/engine/stats.py`
- Update: `ember_memory/server.py`
- Update: `setup_wizard.py`
- Update: `ui.html`
- Test: `tests/test_search_with_engine.py`
- Test: `tests/test_server_v2.py`
- Test: add UI/backend tests if practical

### Problem

The Ember Engine already computes heat, connection bonus, decay, and
composite score, but most of that intelligence is invisible to users.
The current MCP `memory_find` path also bypasses the unified
engine-aware retrieval flow and goes straight to raw backend search.

### Implementation

- [ ] **Step 1: Extend retrieval results with score diagnostics**

Add an explanation payload to `RetrievalResult`, for example:

```python
score_breakdown = {
    "similarity": 0.72,
    "heat_boost": 0.18,
    "connection_bonus": 0.11,
    "decay_factor": 0.93,
    "composite_score": 0.68,
}
```

This should be populated only when Engine scoring is active and should
degrade cleanly when the engine is unavailable.

- [ ] **Step 2: Add optional retrieval explanation helpers**

Add a formatter or helper layer so result explanations are not rebuilt in
three different places. The goal is one shared source for "why this
surfaced" text.

- [ ] **Step 3: Route MCP search through the unified retrieval path**

Update `ember_memory/server.py` so user-facing memory search can use
`core.search.retrieve()` instead of raw backend-only search when
appropriate. The MCP layer should expose engine-scored, namespace-aware
results rather than bypassing the product moat.

At minimum:
- preserve collection-scoped search behavior
- preserve tags/source output where possible
- ensure composite scoring is available in results

- [ ] **Step 4: Add an explainable search surface**

Choose one of these:
- extend `memory_find` with a `show_reasoning: bool = False` option
- add a separate `memory_explain` tool for score breakdowns

The simpler path is preferred. Avoid fragmenting the search UX if one
tool can do both.

- [ ] **Step 5: Add controller API methods for visible engine data**

Expose read-only controller methods for:
- top hot memories
- top connections
- recent engine activity or latest retrieval snapshots
- score breakdown for a selected memory/result

If retrieval history does not yet exist, add only the minimum state
needed for a useful first dashboard. Do not build a large analytics
schema unless the first UI requires it.

- [ ] **Step 6: Upgrade the controller dashboard**

Update `ui.html` and `setup_wizard.py` so the first visible-engine pass
includes:
- a readable "hot right now" panel
- top connection pairs or clusters
- score explanation for selected results
- clearer copy around what heat / connection / freshness mean

The goal is not a giant dashboard. The goal is one glanceable proof that
the engine is adapting.

- [ ] **Step 7: Add tests**

Test:
- score diagnostics are present when Engine scoring runs
- MCP search returns engine-scored results
- explanation output is stable and human-readable
- controller API methods return empty-safe payloads

### Notes

- This task is the fastest path to screenshots and trust.
- The first version does **not** need a perfect Ember Map. A simpler
  ranked view is acceptable if it lands faster.

---

## Task 2: Resurrection Onboarding Flow

**Outcome:** Users can bring old work into `ember-memory` and get to a
"holy shit, it remembers" moment quickly.

**Files:**
- Update: `ember_memory/ingest.py`
- Update: `setup_wizard.py`
- Update: `ui.html`
- Update: `README.md`
- Update: `PRIVACY.md` if import behavior changes meaningfully
- Update: integration docs where import paths are mentioned
- Test: `tests/test_search.py`
- Test: add ingest/controller tests as needed

### Problem

The ingestion pipeline exists, but it is positioned as a utility, not a
first-run experience. The brainstorm identified resurrection of dead
chats, notes, and docs as the strongest emotional onboarding hook.

### Implementation

- [ ] **Step 1: Define the first supported resurrection paths**

Do not try to support every format in one pass. Pick a narrow but strong
first set:
- exported AI chats already compatible with current ingest flow
- markdown/text docs
- optionally a clearly documented CinderACE export path

Write down the supported formats explicitly in docs and UI.

- [ ] **Step 2: Add a first-run import mode to the controller**

In `setup_wizard.py` / `ui.html`, add a guided import path that asks:
- what do you want to revive?
- where is it located?
- which collection should it land in?
- what happens next?

The important part is emotional clarity, not wizard complexity.

- [ ] **Step 3: Improve ingest summaries**

After import, show:
- files or conversations imported
- memories created
- collections affected
- suggested next question to ask

The UI should hand the user directly into the first retrieval moment.

- [ ] **Step 4: Add a "first query" bridge**

After import completes, present one or two suggested prompts such as:
- "What decisions have we already made about X?"
- "What changed across these conversations?"
- "What did we previously learn about this bug?"

This is where resurrection becomes a product moment instead of a backend
operation.

- [ ] **Step 5: Tighten README onboarding copy**

Update `README.md` so one of the primary onboarding paths is:
- import your old context
- ask one question
- recover forgotten work

This should sit beside the fresh-install story, not replace it.

- [ ] **Step 6: Add tests**

Test:
- import flow preserves metadata cleanly
- imported content is searchable through the unified retrieval path
- controller import API returns clear summaries

### Notes

- This task should stay local-first and privacy-forward.
- If CinderACE is mentioned, do it as a helpful pipeline, not as a hard
  dependency.

---

## Task 3: Portable Brain Polish

**Outcome:** The cross-AI continuity story becomes more concrete in the
product and docs without requiring a large new backend system.

**Files:**
- Update: `README.md`
- Update: `ember_memory/server.py`
- Update: `integrations/claude_code/README.md`
- Update: `integrations/gemini_cli/README.md`
- Update: `integrations/codex/README.md`
- Optional create/update: helper module for hand-off packet formatting
- Test: `tests/test_server_v2.py`
- Test: integration tests if practical

### Problem

`ember-memory` already has real multi-CLI architecture, but the user
experience still reads more like "several integrations exist" than "your
memory follows you everywhere."

### Implementation

- [ ] **Step 1: Define the first continuity interaction**

Pick one concrete flow that proves the claim. Recommended:
- a hand-off summary or continuity packet generated from recent results
- or a focused "what changed since last time?" retrieval format

Do **not** try to build full collaborative team memory here.

- [ ] **Step 2: Add a lightweight hand-off surface**

Add one MCP-facing capability or helper that produces a compact,
portable summary with:
- key retrieved memories
- notable sources or collections
- top linked topics
- suggested next questions

This can live as:
- an option on existing search
- or a dedicated helper/tool if that stays cleaner

- [ ] **Step 3: Align the integration docs around one promise**

Update CLI integration READMEs and root messaging so they clearly state
that:
- shared collections carry context across tools
- AI-private collections remain private
- hand-off and continuity are first-class use cases

- [ ] **Step 4: Add one concrete cross-AI walkthrough**

Document a short flow such as:
1. Store or ingest context in Claude Code
2. Search or continue the work from Gemini or Codex
3. Show that the same project memory is available there

This is partly docs, partly proof, and partly marketing collateral.

- [ ] **Step 5: Add tests**

Test:
- shared namespace retrieval works across AI IDs
- private namespaces remain isolated
- the chosen continuity packet/summary format is stable

### Notes

- This is polish, not a massive new architecture task.
- The key job is making the existing continuity story feel deliberate.

---

## Task 4: Release-Layer Messaging Pass

**Outcome:** The docs and product surfaces reflect the new product shape
rather than describing `ember-memory` as a generic RAG utility.

**Files:**
- Update: `README.md`
- Update: `docs/superpowers/specs/2026-03-24-ember-memory-v2-design.md` if needed
- Update: any landing/demo copy surfaced in the controller

### Implementation

- [ ] **Step 1: Keep the three headline candidates visible during copy work**

Primary candidates:
- "Switch AIs without losing your brain."
- "Bring your dead chats back to life."
- "Watch your project memory learn what matters."

- [ ] **Step 2: Reframe the README around the three threads**

The README should more clearly express:
- continuity
- resurrection
- visible adaptation

- [ ] **Step 3: Ensure screenshots/demo flows match the copy**

Do not claim a visible engine if the product offers no visible proof.
Do not claim resurrection if the import flow still feels buried.

---

## Recommended Execution Sequence

1. Ship `Visible Engine` phase 1 with X-Ray and controller surfacing
2. Ship `Resurrection` import flow and first-query bridge
3. Ship `Portable Brain` hand-off polish and docs alignment
4. Refresh README and release messaging around the finished surfaces

This keeps the work grounded in real product proof instead of marketing
aspiration.

---

## Not In This Plan

Hold these for later unless they become necessary to support the first
wave:

- shared team memory / enterprise dashboards
- memory pet / avatar systems
- public memory gardens
- heavy gamification
- broad plugin ecosystems
- deep analytics or telemetry products

These are valid future branches. They are not required to make the first
release feel distinct and lovable.
