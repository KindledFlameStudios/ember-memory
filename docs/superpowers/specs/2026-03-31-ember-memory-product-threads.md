# Ember Memory — Product Threads and Release Hooks

**Date:** 2026-03-31
**Authors:** Justin, Kael, Seren, Solace
**Status:** Brainstorm synthesis, approved as direction-setting reference

## Purpose

This document captures the outcome of the March 31 Forge brainstorm for
`ember-memory`.

The goal of the session was not to redesign the technical core. The
technical core is already strong. The goal was to identify the missing
product hooks, emotional entry points, and sticky surface area that can
help `ember-memory` get attention as a free release before `CinderVOX`.

This is the reference for how to shape the product outwardly from here.

## Core Conclusion

The brainstorm converged on a clear product shape:

**Ember Memory is a local-first continuity engine that revives old
context, follows you across AIs, and visibly learns what matters.**

That breaks into three primary product threads:

1. **Portable Brain** — your memory follows you across Claude Code,
   Gemini CLI, and Codex.
2. **Visible Engine** — the Ember Engine should be surfaced so users can
   see why memory is adapting and trust what it returns.
3. **Resurrection** — importing old chats, notes, and docs should create
   a strong first-run moment where forgotten work becomes useful again.

These three threads are the strongest because they combine:

- high emotional energy
- real user value
- strong differentiation
- existing implementation head start

## Product Threads

### 1. Portable Brain

**Pattern:** Continuity across tools, sessions, and eventually people.

**Promise:** Switch AIs without losing your brain.

### Why it has energy

- It is the cleanest headline in the room.
- It turns multi-CLI support into a category claim instead of a checklist
  item.
- It speaks directly to a common pain: every AI tool acts like your work
  started five minutes ago.

### Why it is feasible

- Multi-CLI architecture already exists.
- Namespacing and shared collections already exist.
- The gaps are product polish and transfer experience, not a full
  rewrite.

### Key manifestations

- Memory shared across Claude Code, Gemini CLI, and Codex
- Better cross-AI hand-off flows
- Narrative context transfer instead of raw dumps
- Portable exports/imports that preserve memory value

### Why it matters strategically

This is the clearest differentiator against tool-specific memory
systems. It is also the cleanest bridge from personal memory to future
team continuity.

### 2. Visible Engine

**Pattern:** Explainable, inspectable, screenshotable intelligence.

**Promise:** Watch your project memory learn what matters.

### Why it has energy

- Everyone independently reached for ways to make the engine visible:
  X-Ray, Ember Score, diffs, pulse, map, heartbeat, pet, ghost layer.
- The hidden engine is the moat. If it stays invisible, users only feel
  it indirectly.
- It creates habit and trust at the same time.

### Why it is feasible

- Heat, connections, freshness, and scoring already exist in the engine.
- Much of this thread is surfacing existing state rather than inventing
  new logic.
- Even the first useful version is small.

### Key manifestations

- **Memory X-Ray**: explain why a result surfaced
- **Weekly Diff / Pulse**: what heated up, cooled down, or connected
- **Ember Map**: a visual memory field or graph
- **Project Heartbeat**: what the project brain is hottest around right
  now

### Why it matters strategically

This is both a trust layer and a growth layer.

Trust:
- users can verify retrieval behavior
- adaptive scoring stops feeling magical and starts feeling credible

Growth:
- images and diffs are shareable
- the product becomes easier to demonstrate
- the engine gains visible character

### 3. Resurrection

**Pattern:** Recovering old work and turning it back into live context.

**Promise:** Bring your dead chats back to life.

### Why it has energy

- It creates an emotional first-run experience instead of a purely
  technical one.
- It makes old effort feel preserved rather than wasted.
- It pairs naturally with CinderACE as a pipeline: export, ingest,
  remember.

### Why it is feasible

- Ingestion already exists.
- The main missing piece is packaging the import path as a compelling
  onboarding experience.
- The first version can be narrow and still land.

### Key manifestations

- Import old AI chat exports
- Ingest docs, notes, issue history, and prior conversations
- Ask one question and receive an answer stitched from forgotten prior
  work
- Optional archaeology or timelapse views later

### Why it matters strategically

This is the strongest emotional onboarding hook and the clearest
cross-sell bridge to CinderACE.

## The Shape Underneath

These three threads are not random feature buckets. They form a product
triangle:

- **Portable Brain** = continuity
- **Visible Engine** = trust and habit
- **Resurrection** = emotional onboarding

Together they answer three different adoption questions:

- Why should I install this?
- Why should I trust it?
- Why should I care right away?

## Priority Read

### Most feasible near-term

**Visible Engine**

This has the lowest implementation risk because the underlying signals
already exist. It is the most obvious place to get more product value
without destabilizing the core.

### Strongest onboarding hook

**Resurrection**

This is the clearest path to a memorable first experience. It also gives
the marketing copy emotional weight instead of only technical claims.

### Strongest long-term positioning

**Portable Brain**

This is the biggest category statement and the most durable strategic
claim, even if parts of the experience still need polish.

## Recommended Build Order

1. **Visible Engine first**
2. **Resurrection second**
3. **Portable Brain polish third**

Reasoning:

- Visible Engine is the fastest path to trust, screenshots, and a more
  legible moat.
- Resurrection is the strongest onboarding and CinderACE linkage.
- Portable Brain is already substantively true, but needs smoother
  transfer flows before it fully feels like a polished promise.

## Release Messaging Candidates

The brainstorm surfaced three headline-quality messages:

- **Switch AIs without losing your brain.**
- **Bring your dead chats back to life.**
- **Watch your project memory learn what matters.**

These should be treated as serious copy candidates, not throwaway
brainstorm lines.

## Feature Buckets

### Tier 1: Strong Candidates for Early Build

- Memory X-Ray
- Weekly Pulse / Memory Diff
- Ember Map or another lightweight visual memory view
- Import flow for old chat exports
- Stronger first-run magic around ingest + first query
- Better cross-AI hand-off / continuity framing
- Canonical or high-trust memory labeling
- Memory repair actions: outdated, superseded, canonical, wrong

### Tier 2: Strong, But After the Core Shape Lands

- Session-end save prompt / "carry forward" ritual
- "What changed since last time?" orientation flow
- Project heartbeat dashboard
- Memory trails and lineage browsing
- Memory kits / cold start packs
- Human-facing desktop search or personal search layer

### Tier 3: Nice Later / Character Layer

- Memory pet / avatar
- Dream journal resurfacing mode
- Garden-style public showcases
- Heavier gamification or streak cosmetics

These are not bad ideas. They simply should not blur the core claim in
the first public push.

## Strategic Guardrails

- Do not ship a bag of charming features with no center.
- Do not bury the Ember Engine behind purely technical language.
- Do not make the free version feel like a crippled funnel.
- Do not over-index on enterprise/team features before the personal
  experience is lovable.
- Do make the first-run moment emotionally satisfying.
- Do make at least one part of the engine visible and explainable.
- Do preserve the local-first, private-by-default trust story.

## Positioning Summary

`ember-memory` should be presented as more than a vector-backed RAG
utility.

It is:

- a **continuity layer** across AI tools
- a **revival tool** for old context and forgotten work
- an **adaptive memory engine** with visible signals

That is the differentiating shape that came out of the session.

## Next Planning Step

The next planning pass should convert this document into a practical
execution stack:

1. choose the first 2-3 user-facing hooks to ship
2. map each hook to concrete backend/UI/doc tasks
3. decide what belongs in free v1 versus later expansion
4. update README and release messaging to reflect the chosen shape
