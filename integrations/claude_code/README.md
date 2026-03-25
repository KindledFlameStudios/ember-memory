# Claude Code Integration

Ember Memory integration for Claude Code.

## Files
- `plugin.json` — Claude Code plugin manifest
- `hooks.json` — UserPromptSubmit hook configuration
- `.mcp.json` — MCP server registration

## Hook
The hook fires on every user message, calling `core.search.retrieve()` with `ai_id="claude"`.
Context is injected via `<ember-memory>` tags in stdout.
