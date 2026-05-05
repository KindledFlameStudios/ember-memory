# Privacy Policy — Ember Memory

**Last updated:** May 5, 2026

## The short version

Ember Memory runs entirely on your machine by default. Kindled Flame Studios collects nothing from the app.

## Data storage

All application data is stored locally in your home directory (`~/.ember-memory/` by default). This includes:
- ChromaDB vector database files
- Configuration settings
- Activity logs (query timestamps and hit counts only, stored locally)

## Data transmission

Ember Memory makes zero external network requests by default. The default embedding provider is your local Ollama instance (`localhost:11434`).

If you configure OpenAI, Google, or OpenRouter embeddings, the text being embedded is sent to that provider's API using your own API key. This is opt-in and not the default behavior. Memory data still remains stored locally unless you configure a cloud storage backend yourself.

## Data collection

Kindled Flame Studios collects no data from Ember Memory users. There is no telemetry, no analytics, no usage tracking, no crash reporting, and no phone-home behavior of any kind.

## Third-party services

- **Ollama** — Runs locally on your machine. See [Ollama's privacy policy](https://ollama.com/privacy) for their software.
- **ChromaDB** — Runs locally as an embedded database. No network activity. See [ChromaDB's documentation](https://docs.trychroma.com/).
- **OpenAI / Google / OpenRouter** — Optional embedding providers. Used only if you configure them.
- **Qdrant / Weaviate / Pinecone / pgvector** — Optional storage backends. Used only if you configure them.

## Your data, your control

You can delete all Ember Memory data at any time by removing the `~/.ember-memory/` directory. There is nothing to "deactivate" or "request deletion" from any server because no server was ever involved.

## Contact

Questions about this policy: support@kindledflamestudios.com

Kindled Flame Studios — https://kindledflamestudios.com
