# Gemini CLI Integration

Full auto-retrieval integration for Google's Gemini CLI.

## What You Get

- **Auto-retrieval** on every message via `BeforeAgent` hook
- **MCP tools** for manual store, search, and hand-off
- **Ember Engine** scoring adapts to your workflow
- **Shared + private collections** — project knowledge flows across CLIs

## Cross-CLI Continuity

Work started in Claude Code? Switch to Gemini — your shared project memories are already here. Private collections stay private to each CLI.

Generate a hand-off packet in Claude Code with `memory_handoff`, then pick it up here.

## Setup

Recommended:

```bash
ember-memory
```

Open **CLI Status**, click **Run Install**, then click **Test Hooks**.

Manual setup:

Add to `~/.gemini/settings.json`:

```json
{
  "hooks": {
    "BeforeAgent": [{
      "matcher": "*",
      "hooks": [{
        "name": "ember-memory",
        "type": "command",
        "command": "ember-memory-gemini-hook",
        "timeout": 10000
      }]
    }]
  },
  "mcpServers": {
    "ember-memory": {
      "command": "python3",
      "args": ["-m", "ember_memory.server"],
      "env": {"EMBER_AI_ID": "gemini"},
      "timeout": 30000
    }
  }
}
```

Note: Use hyphens in MCP server names, not underscores.
