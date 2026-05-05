# Ember Memory — Troubleshooting Guide

**Common issues and solutions for installation, configuration, and daily use.**

---

## Installation Issues

### Ollama Not Found

**Error:** `Ollama: Not installed — ollama.com`

**Solution:**
1. Download from [ollama.com](https://ollama.com)
2. Install and start the service:
   ```bash
   # Linux
   ollama serve &
   
   # macOS
   ollama serve &
   
   # Windows (PowerShell)
   Start-Process ollama serve
   ```
3. Pull the embedding model:
   ```bash
   ollama pull bge-m3
   ```

### Model Not Found

**Error:** `Not found. Run: ollama pull bge-m3`

**Solution:**
```bash
ollama pull bge-m3
```

If you're using a different model, update your config:
```bash
# Edit ~/.ember-memory/config.env
EMBER_EMBEDDING_MODEL=your-model-name
```

### ChromaDB Import Error

**Error:** `chromadb: pip install chromadb`

**Solution:**
```bash
pip install chromadb
# or
pip install -e ".[chromadb]"
```

### MCP Not Found

**Error:** `mcp: pip install 'mcp[cli]'`

**Solution:**
```bash
pip install 'mcp[cli]'
```

---

## CLI Integration Issues

### Claude Code MCP Not Configured

**Error:** `claude_mcp: False`

**Solution:**
1. Check if `~/.claude.json` exists
2. Open the controller: `ember-memory` for app mode, or `ember-memory controller` / `ember-memory-controller` for foreground troubleshooting
3. Open **CLI Status**
4. Click **Run Install** — this auto-registers the MCP server
5. Click **Test Hooks** to verify the install

**Manual fix:**
Add to `~/.claude.json`:
```json
{
  "mcpServers": {
    "ember-memory": {
      "command": "/path/to/python",
      "args": ["-m", "ember_memory.server"]
    }
  }
}
```

### Claude Code Hook Not Working

**Error:** `claude_hook: False`

**Solution:**
1. Check `~/.claude/settings.json`
2. Ensure the hook is registered under `UserPromptSubmit`
3. Run **CLI Status -> Run Install** to auto-configure
4. Run **Test Hooks** to verify the hook fires

**Manual fix:**
Add to `~/.claude/settings.json`:
```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "ember-memory-claude-hook",
            "timeout": 10
          }
        ]
      }
    ]
  }
}
```

### Gemini CLI Not Detecting Ember Memory

**Error:** `gemini_mcp: False` or `gemini_hook: False`

**Solution:**
1. Ensure Gemini CLI is installed: `gemini --version`
2. Check `~/.gemini/settings.json`
3. Run **CLI Status -> Run Install** to auto-configure
4. Run **Test Hooks** to verify the hook fires

**Note:** Gemini CLI hooks require the `BeforeAgent` hook point. The controller handles this automatically.

### Codex Integration Issues

**Error:** `codex_mcp: False` or `codex_hook: False`

**Solution:**
1. Check `~/.codex/config.toml` exists
2. Check `~/.codex/hooks.json` is properly formatted
3. Ensure the `hooks` feature is enabled in Codex
4. Run **CLI Status -> Run Install**, then **Test Hooks**

**Manual fix:**
Add to `~/.codex/hooks.json`:
```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "ember-memory-codex-hook",
            "timeout": 10
          }
        ]
      }
    ]
  }
}
```

---

## Memory Retrieval Issues

### No Memories Found

**Error:** `No memories found across any collection.`

**Causes:**
1. No memories have been stored yet
2. Searching the wrong collection
3. Similarity threshold too high

**Solutions:**
1. Store your first memory:
   ```python
   memory_store(content="Your architecture decision here", collection="architecture")
   ```
2. Search all collections:
   ```python
   memory_find(query="your query", collection="*")
   ```
3. Lower the similarity threshold in `~/.ember-memory/config.env`:
   ```
   EMBER_SIMILARITY_THRESHOLD=0.35
   ```

### Memories Not Appearing in AI Context

**Issue:** AI doesn't see relevant memories automatically

**Causes:**
1. Hook not installed correctly
2. Memory score below auto-retrieval threshold
3. AI is ignored in heat dashboard

**Solutions:**
1. Verify hooks are installed: open **CLI Status** and run **Test Hooks**
2. Check memory heat — if heat is 0, the memory may not surface
3. Ensure the AI is not marked as "ignored" in settings

### Heat Map Shows No Data

**Issue:** Dashboard shows "The Engine is still learning your patterns"

**Causes:**
1. No retrieval events have occurred yet
2. Heat decay has cooled all entries
3. AI filter is set to an ignored AI

**Solutions:**
1. Use the AI CLI normally — heat builds from usage
2. Check the AI filter in the dashboard (top-left dropdown)
3. Verify heat mode in settings (universal vs per-cli)

---

## Performance Issues

### Slow Embedding Generation

**Symptoms:** Embedding takes >5 seconds per query

**Causes:**
1. Ollama is running slow
2. Model is too large for your hardware
3. Network latency (if using cloud embeddings)

**Solutions:**
1. Check Ollama is running locally: `ollama list`
2. Try a smaller model: `ollama pull nomic-embed-text`
3. If using cloud embeddings, check your internet connection

### Slow Vector Search

**Symptoms:** Search takes >2 seconds

**Causes:**
1. Large collection (>10,000 entries)
2. ChromaDB needs optimization
3. Too many collections being searched

**Solutions:**
1. Use collection-specific searches instead of `collection="*"`
2. Increase similarity threshold to reduce candidate results
3. Consider switching to LanceDB for better performance:
   ```bash
   pip install lancedb
   # Update config.env: EMBER_BACKEND=lancedb
   ```

---

## Configuration Issues

### Config File Not Found

**Error:** `~/.ember-memory/config.env` missing

**Solution:**
1. Open the controller — it creates the config automatically
2. Or create manually:
   ```bash
   mkdir -p ~/.ember-memory
   touch ~/.ember-memory/config.env
   ```
3. Add base config:
   ```
   EMBER_DATA_DIR=/home/username/.ember-memory
   EMBER_BACKEND=chromadb
   EMBER_EMBEDDING_PROVIDER=ollama
   ```

### Wrong Data Directory

**Issue:** Memories stored in unexpected location

**Solution:**
1. Check `EMBER_DATA_DIR` in `~/.ember-memory/config.env`
2. Update if needed:
   ```
   EMBER_DATA_DIR=/new/path/to/data
   ```
3. Restart the controller and your AI CLIs

### Environment Variables Not Applying

**Issue:** Changed config but behavior hasn't changed

**Solution:**
1. Restart your AI CLI (Claude Code, Gemini, Codex)
2. Restart the Ember Memory controller
3. Verify the config file was saved correctly

---

## Advanced Issues

### Custom CLI Integration

**Question:** Can I use Ember Memory with a CLI not listed?

**Answer:** Yes! Add a custom CLI in the controller settings:
1. Open the controller
2. Go to Settings → Custom CLIs
3. Add your CLI ID and name
4. Configure the hook manually in your CLI's config

### Switching Embedding Providers

**Question:** How do I switch from Ollama to OpenAI?

**Solution:**
1. Edit `~/.ember-memory/config.env`:
   ```
   EMBER_EMBEDDING_PROVIDER=openai
   EMBER_OPENAI_API_KEY=<your-openai-key>
   EMBER_OPENAI_EMBEDDING_MODEL=text-embedding-3-small
   ```
2. Restart the controller
3. Existing memories remain — no migration needed

### Database Backend Migration

**Question:** How do I switch from ChromaDB to Qdrant?

**Solution:**
1. Install Qdrant:
   ```bash
   pip install qdrant-client
   ```
2. Update config:
   ```
   EMBER_BACKEND=qdrant
   EMBER_QDRANT_URL=http://localhost:6333
   ```
3. **Note:** Existing memories won't migrate automatically. You'll need to:
   - Export from ChromaDB
   - Re-ingest into Qdrant
   - Or start fresh

### Heat Decay Tuning

**Question:** Can I adjust how fast heat decays?

**Answer:** Yes, edit `ember_memory/core/engine/heat.py`:
```python
DECAY_ACTIVE = 0.92      # Adjust (lower = faster decay)
DECAY_INACTIVE = 0.60    # Adjust (lower = faster decay)
TIME_DECAY_FACTOR = 0.95 # Adjust (lower = faster decay)
TIME_DECAY_INTERVAL_MINUTES = 15  # Adjust interval
```

**Note:** This requires code changes. Future versions may expose this via config.

---

## Getting Help

If your issue isn't covered here:

1. **Check the logs:**
   ```bash
   # Controller logs
   tail -f ~/.ember-memory/controller.log
   
   # MCP server logs (varies by CLI)
   ```

2. **Verify your installation:**
   ```bash
   ember-memory  # Open the app
   # Open CLI Status
   # Click "Run Install"
   # Click "Test Hooks"
   ```

3. **Open a GitHub issue** with:
   - Your OS and Python version
   - Error messages (full text)
   - What you were trying to do
   - What you expected to happen

4. **Join the community** (if/when we have Discord/forums)

---

*Last updated: May 5, 2026*
