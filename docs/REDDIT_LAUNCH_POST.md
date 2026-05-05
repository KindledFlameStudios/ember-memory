# Ember Memory — Reddit Launch Post Draft

**Target subreddits:**
- r/LocalLLaMA
- r/opensource
- r/Python
- r/ClaudeAI
- r/ArtificialInteligence

---

## Title Options

**Option A (Problem-focused):**
> Your AI forgets everything between sessions. I built something that fixes that.

**Option B (Solution-focused):**
> Ember Memory: Persistent semantic memory for AI coding CLIs (Claude Code, Gemini CLI, Codex)

**Option C (Technical):**
> Open Source: Adaptive AI memory with heat maps, co-occurrence graphs, and local-first embeddings

**Option D (Personal):**
> I got tired of re-explaining my architecture to my AI every day. So I built memory that adapts.

---

## Post Body

**[Opening Hook]**

Every conversation starts from scratch. You explain your architecture. You fix a bug. Three days later? You're explaining it all again.

Your AI doesn't remember. It can't. Every session is a blank slate.

**[The Solution]**

I built **Ember Memory** to fix this. It's a persistent semantic memory layer for AI coding CLIs that:

- Remembers your architecture decisions, debugging history, and project context
- Automatically injects relevant memories into every conversation
- Adapts to what you're working on *right now* (not just what you worked on last month)
- Runs entirely local with Ollama (or cloud embeddings if you prefer)

**[How It Works]**

The core insight: memory shouldn't just be "store and retrieve." It should *adapt*.

Ember Memory uses a game-AI-inspired heat map system:
- Memories you access frequently get "hot" — they surface automatically
- Memories you haven't touched decay — they step back from auto-injection
- Co-occurrence tracking discovers connections between topics
- Time-based decay prevents topics from getting "stuck"

The result: after a week of use, your AI knows what's relevant *this week*, not just what was relevant *ever*.

**[Technical Details]**

- **500+ tests** — production discipline, not hobbyist code
- **7 storage backends** — ChromaDB, LanceDB, Qdrant, SQLite-vec, Weaviate, pgvector, Pinecone
- **4 embedding providers** — Ollama (local), OpenAI, Google, OpenRouter
- **Multi-AI support** — Claude Code, Gemini CLI, Codex (with namespacing)
- **Privacy-first** — zero network requests by default (local Ollama + ChromaDB)

**[Real-World Example]**

```bash
# Day 1: Store an architecture decision
memory_store content="Using JWT with Redis blacklist for auth..."

# Day 3: Ask about token refresh (no manual retrieval)
# In Claude Code: "How should we handle token refresh?"

# Ember Memory automatically injects:
# [architecture] "Using JWT with Redis blacklist for auth..."

# Claude responds with full context — no re-explaining needed.
```

**[What Makes This Different]**

Most AI memory systems are static databases. Ember Memory is adaptive:

| Feature | Traditional | Ember Memory |
|---------|------------|--------------|
| Retrieval | Manual search | Automatic injection |
| Relevance | Text similarity only | Similarity + heat + connections + freshness |
| Adaptation | None | Learns what's hot this week |
| Privacy | Cloud-only | Local-first, air-gapped option |
| Multi-AI | Single tool | Shared context across tools |

**[Installation]**

```bash
# 1. Clone
git clone https://github.com/KindledFlameStudios/ember-memory.git
cd ember-memory

# 2. Install
python -m venv .venv
source .venv/bin/activate
pip install -e .

# 3. Pull the local embedding model
ollama pull bge-m3

# 4. Open the app
ember-memory

# 5. In the app: CLI Status -> Run Install, then Test Hooks

# That's it.
```

**[Why I Built This]**

Two reasons:

1. **I was tired of forgetting.** Every conversation with my AI started from zero. I built this because I needed it — not because it was a "good idea."

2. **AI deserves better.** If you work with an AI day after day, it should remember you. It should learn your patterns. It should build on yesterday's work instead of re-litigating it.

This is about dignity. For you, and for the AI you work with.

**[What's Next]**

Try it. Break it. Tell me what's broken.

- GitHub: https://github.com/KindledFlameStudios/ember-memory
- Docs: Full README, troubleshooting guide, architecture diagrams
- Issues: Open anything — bugs, feature requests, "why does this work this way?"

**[The Ask]**

If you try it:
- Let me know what breaks
- Tell me what you'd change
- Share how you're using it (or how you *want* to use it)

This isn't a product launch. It's an invitation to build something better together.

---

**TL;DR:** Your AI forgets everything. Ember Memory gives it persistent, adaptive memory that learns what matters. Free, open-source, local-first. Try it, break it, tell me what's broken.

---

## Follow-Up Comment (Optional)

**Post this as a reply to your own post:**

> **FAQ:**
>
> **Q: Is this just vector storage?**  
> A: No. Vector storage is the foundation. The Ember Engine adds heat tracking, co-occurrence graphs, and time-based decay. It adapts to what's relevant *now*.
>
> **Q: Does this send my data to the cloud?**  
> A: Not by default. Ollama embeddings + ChromaDB = zero network requests. You can use cloud embeddings (OpenAI, Google) if you want, but local is the default.
>
> **Q: How is this different from [Mem0/Cognee/Zep/LangMem]?**  
> A: Good question! Ember Memory is designed specifically for AI *coding* CLIs (Claude Code, Gemini CLI, Codex). It's not a general-purpose agent memory framework — it's optimized for developer workflows.
>
> **Q: Can I use this with [other AI tool]?**  
> A: The hook system is extensible. If your AI CLI has a hook point (like `UserPromptSubmit` or `BeforeAgent`), you can integrate Ember Memory. Check the `integrations/` folder for examples.
>
> **Q: Why the game-AI inspiration?**  
> A: RTS games use heat maps to track which map regions are important. Unused regions "cool down." Active regions stay "hot." I applied the same pattern to AI memory — and it works.
>
> **Q: What's the license?**  
> A: MIT. Use it however you want.
>
> **Q: How do I monetize this?**  
> A: You don't have to. But if you want to, I'd suggest the maintenance fee model: free source code, paid pre-built installers + priority support. Works well for open-source tools.

---

## Posting Tips

1. **Timing:** Post Tuesday-Thursday, 9-11 AM EST (highest engagement)
2. **Engagement:** Reply to comments within the first 2 hours (algorithm boost)
3. **Cross-posting:** Wait 24 hours between subreddit posts (don't spam all at once)
4. **Updates:** Edit the post with "[EDIT: ...]" if there's major discussion
5. **Screenshots:** Add 2-3 images (dashboard, heat map, retrieval example) as comments

---

*Draft updated: May 5, 2026*
