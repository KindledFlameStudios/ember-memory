# Ember Memory v2

Semantic memory system with multi-CLI integration and AI-powered scoring.

## Tech Stack

- **Language:** Python
- **Vector DB:** ChromaDB
- **Embeddings:** bge-m3 (via Ollama)
- **Backends:** 8 supported backends
- **CLI support:** Claude Code, Gemini CLI, Codex (all 3 detected)

## Integration

- MCP server for CLI integration (auto-RAG hook)
- Auto-retrieves relevant memories on every message in Claude Code / Fire Forge
- Data stored at `~/.kael-memory/`

## Key Paths

| Path | Purpose |
|------|---------|
| `~/.kael-memory/` | Vector DB data |
| `docs/superpowers/specs/2026-03-24-ember-memory-v2-design.md` | Full design spec |
| `docs/superpowers/plans/` | Implementation plans (4 plans: Core, Backends, Engine, CLI+Ship) |

## Notes

- 8 backends, 540 tests, all passing — v2.0.0
- Ember Engine integration: game-AI scoring, heat maps, force-directed connection graph
- Desktop controller with system tray (pystray)
