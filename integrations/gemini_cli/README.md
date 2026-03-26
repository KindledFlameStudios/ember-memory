# Gemini CLI Integration

Ember Memory integration for Google's Gemini CLI.

## Hook
The `BeforeAgent` hook fires on every user message, calling `core.search.retrieve()` with `ai_id="gemini"`.
Context is injected via `hookSpecificOutput.additionalContext`.

## Setup

Add to `~/.gemini/settings.json`:

```json
{
  "hooks": {
    "BeforeAgent": [
      {
        "matcher": "*",
        "hooks": [
          {
            "name": "ember-memory",
            "type": "command",
            "command": "python3 /path/to/ember-memory/integrations/gemini_cli/hook.py",
            "timeout": 3000
          }
        ]
      }
    ]
  }
}
```

## MCP Server

Add to `~/.gemini/settings.json`:

```json
{
  "mcpServers": {
    "ember-memory": {
      "command": "python3",
      "args": ["-m", "ember_memory.server"],
      "timeout": 30000
    }
  }
}
```

Note: Do NOT use underscores in the MCP server alias name — use hyphens instead.
