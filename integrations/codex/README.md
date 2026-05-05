# Codex Integration

Ember Memory integration for OpenAI's Codex CLI.

## What You Get

- **MCP tools** for store, search, hand-off, and collection management
- **Ember Engine** scoring on all searches — adapts to your workflow
- **Shared collections** — project knowledge from Claude Code and Gemini CLI is available here
- **Auto-retrieval** via Codex lifecycle hooks

## Current Status

| Feature | Status |
|---------|--------|
| MCP tools (store/search/manage) | Full support |
| Engine scoring on searches | Full support |
| Auto-retrieval | Full support via `UserPromptSubmit` hook |
| Per-session heat isolation | Full support |

Codex displays ember-memory results as an inline block in chat, giving visibility into what memories are being retrieved.

## Cross-CLI Continuity

Decisions stored in Claude Code? Architecture docs from Gemini? They're here in your shared collections. Use `memory_handoff` to generate a context summary from another CLI session.

## Setup

Recommended:

```bash
ember-memory
```

Open **CLI Status**, click **Run Install**, then click **Test Hooks**.

Manual setup:

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

[features]
codex_hooks = true
```

Add `~/.codex/hooks.json`:

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "ember-memory-codex-hook",
            "timeout": 10,
            "statusMessage": "Retrieving Ember Memory context"
          }
        ]
      }
    ]
  }
}
```

## Works With AGENTS.md

Codex loads `AGENTS.md` at session start for static context. Ember Memory adds dynamic, searchable memory on top. They complement each other — static identity + adaptive retrieval.
