# Claude Code Integration

Full auto-retrieval integration for Claude Code.

## What You Get

- **Auto-retrieval** on every message via `UserPromptSubmit` hook
- **MCP tools** for manual store, search, and hand-off
- **Ember Engine** scoring — heat, connections, decay adapt to your workflow
- **Shared + private collections** — your AI-specific knowledge stays private, project knowledge is shared across CLIs

## How It Works

1. You send a message in Claude Code
2. The hook embeds your message and searches all visible collections
3. The Engine re-scores results using heat, connections, and decay
4. Relevant memories appear in your AI's context as `<ember-memory>` tags
5. Your AI responds with context it shouldn't have — because it remembers

## Cross-CLI Continuity

Memories stored here are available in Gemini CLI and Codex too (shared collections). Work in Claude Code all morning, switch to Gemini for a frontend pass — your project context follows.

Use `memory_handoff` to generate a portable context summary for another CLI to pick up.

## Setup

```bash
python -m ember_memory setup
```

Or manually — add to `~/.claude/settings.json`:
```json
{
  "hooks": {
    "UserPromptSubmit": [{
      "matcher": "*",
      "hooks": [{"type": "command", "command": "python3 /path/to/ember-memory/ember_memory/hook.py", "timeout": 10}]
    }]
  }
}
```

## Files
- `plugin.json` — Claude Code plugin manifest
- `hooks.json` — UserPromptSubmit hook configuration
- `.mcp.json` — MCP server registration
