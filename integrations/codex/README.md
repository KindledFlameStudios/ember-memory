# Codex Integration

Ember Memory integration for OpenAI's Codex CLI.

## Status

**MCP tools: Fully supported.** Your AI can store, search, and manage memories via MCP tool calls.

**Auto-retrieval: Not yet available.** Codex hooks are experimental and currently cannot inject context into the model's prompt. When Codex ships a stable pre-prompt hook with context injection, an auto-retrieval adapter will be added (~50 lines).

## MCP Setup

Add to `~/.codex/config.toml`:

```toml
[mcp_servers.ember-memory]
command = "python3"
args = ["-m", "ember_memory.server"]
startup_timeout_sec = 15
tool_timeout_sec = 30

[mcp_servers.ember-memory.env]
EMBER_DATA_DIR = "~/.ember-memory"
EMBER_AI_ID = "codex"
```

For project-scoped config, add to `.codex/config.toml` (requires trusted project).

## Usage

Once configured, your AI can use these tools directly:

- **"Remember that we're using Redis for caching"** → calls `memory_store`
- **"What do we know about the auth system?"** → calls `memory_find`
- **"Show my memory collections"** → calls `list_collections`

The Ember Engine scoring (heat, connections, decay) applies to all manual searches — memories you reference often will still rank higher over time.

## AGENTS.md Compatibility

Codex loads `AGENTS.md` at session start for static context. Ember Memory is complementary — it provides dynamic, searchable memory via MCP tools during the session. They don't conflict.
