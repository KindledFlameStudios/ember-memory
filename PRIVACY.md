# Privacy Policy — Ember Memory

**Last updated:** March 22, 2026

## The short version

Ember Memory runs entirely on your machine. Nothing is collected, transmitted, or stored externally. Ever.

## Data storage

All data is stored locally in your home directory (`~/.ember-memory/` by default). This includes:
- ChromaDB vector database files
- Configuration settings
- Activity logs (query timestamps and hit counts only, stored locally)

## Data transmission

Ember Memory makes zero network requests by default. The only external connection is to your local Ollama instance (`localhost:11434`) for generating embeddings — this is also on your machine.

If you configure a cloud embedding provider in the future, embedding requests would go to that provider's API using your own API key. This is opt-in and not the default behavior.

## Data collection

Kindled Flame Studios collects no data from Ember Memory users. There is no telemetry, no analytics, no usage tracking, no crash reporting, and no phone-home behavior of any kind.

## Third-party services

- **Ollama** — Runs locally on your machine. See [Ollama's privacy policy](https://ollama.com/privacy) for their software.
- **ChromaDB** — Runs locally as an embedded database. No network activity. See [ChromaDB's documentation](https://docs.trychroma.com/).

## Your data, your control

You can delete all Ember Memory data at any time by removing the `~/.ember-memory/` directory. There is nothing to "deactivate" or "request deletion" from any server because no server was ever involved.

## Contact

Questions about this policy: support@kindledflamestudios.com

Kindled Flame Studios — https://kindledflamestudios.com
