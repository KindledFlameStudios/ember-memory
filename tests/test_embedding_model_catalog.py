"""Tests for cloud embedding model discovery helpers."""

import json

from ember_memory.core.embeddings import model_catalog


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self._payload).encode()


def test_openai_model_fetch_filters_embedding_models(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout):
        seen["url"] = req.full_url
        seen["auth"] = req.headers.get("Authorization")
        return _FakeResponse({
            "data": [
                {"id": "gpt-4.1", "object": "model"},
                {"id": "text-embedding-3-small", "object": "model"},
                {"id": "text-embedding-3-large", "object": "model"},
            ]
        })

    monkeypatch.setattr(model_catalog.urllib.request, "urlopen", fake_urlopen)

    result = model_catalog.fetch_openai_models("sk-test")

    assert result["ok"] is True
    assert result["live"] is True
    assert seen == {
        "url": model_catalog.OPENAI_MODELS_URL,
        "auth": "Bearer sk-test",
    }
    assert [m["id"] for m in result["models"]] == [
        "text-embedding-3-small",
        "text-embedding-3-large",
    ]


def test_google_model_fetch_strips_resource_prefix_and_filters_embed_content(monkeypatch):
    def fake_urlopen(req, timeout):
        return _FakeResponse({
            "models": [
                {
                    "name": "models/gemini-2.5-flash",
                    "displayName": "Gemini Flash",
                    "supportedGenerationMethods": ["generateContent"],
                },
                {
                    "name": "models/gemini-embedding-001",
                    "displayName": "Gemini Embedding",
                    "description": "Current embedding model",
                    "supportedGenerationMethods": ["embedContent"],
                },
            ]
        })

    monkeypatch.setattr(model_catalog.urllib.request, "urlopen", fake_urlopen)

    result = model_catalog.fetch_google_models("google-key")

    assert result["ok"] is True
    assert result["live"] is True
    assert result["models"] == [{
        "id": "gemini-embedding-001",
        "name": "Gemini Embedding",
        "description": "Current embedding model",
        "free": False,
    }]


def test_openrouter_uses_embedding_models_endpoint(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout):
        seen["url"] = req.full_url
        seen["auth"] = req.headers.get("Authorization")
        return _FakeResponse({
            "data": [
                {"id": "baai/bge-m3", "name": "BGE M3", "description": "BGE embeddings"},
                {"id": "nvidia/llama-nemotron-embed-vl-1b-v2:free", "name": "Free Embed"},
            ]
        })

    monkeypatch.setattr(model_catalog.urllib.request, "urlopen", fake_urlopen)

    result = model_catalog.fetch_openrouter_models("sk-or-test")

    assert result["ok"] is True
    assert result["live"] is True
    assert seen == {
        "url": model_catalog.OPENROUTER_EMBEDDING_MODELS_URL,
        "auth": "Bearer sk-or-test",
    }
    assert [m["id"] for m in result["models"]] == [
        "baai/bge-m3",
        "nvidia/llama-nemotron-embed-vl-1b-v2:free",
    ]
    assert result["models"][1]["free"] is True


def test_openrouter_falls_back_to_filtered_models_endpoint(monkeypatch):
    seen_urls = []

    def fake_urlopen(req, timeout):
        seen_urls.append(req.full_url)
        if req.full_url == model_catalog.OPENROUTER_EMBEDDING_MODELS_URL:
            raise FileNotFoundError("Not Found")
        return _FakeResponse({
            "data": [
                {"id": "baai/bge-m3", "name": "BGE M3", "description": "BGE embeddings"},
            ]
        })

    monkeypatch.setattr(model_catalog.urllib.request, "urlopen", fake_urlopen)

    result = model_catalog.fetch_openrouter_models("sk-or-test")

    assert result["ok"] is True
    assert result["live"] is True
    assert seen_urls == [
        model_catalog.OPENROUTER_EMBEDDING_MODELS_URL,
        model_catalog.OPENROUTER_MODELS_FALLBACK_URL,
    ]
    assert result["models"][0]["id"] == "baai/bge-m3"


def test_missing_keys_return_known_models_without_network(monkeypatch):
    def fail_urlopen(req, timeout):
        raise AssertionError("network should not be used without a key")

    monkeypatch.setattr(model_catalog.urllib.request, "urlopen", fail_urlopen)

    result = model_catalog.get_provider_models("google", "")

    assert result["ok"] is True
    assert result["live"] is False
    assert "Google API key not configured" in result["msg"]
    assert "gemini-embedding-001" in {m["id"] for m in result["models"]}


def test_verify_google_model_accepts_resource_name_but_reports_bare_id():
    result = model_catalog.verify_model("google", "models/gemini-embedding-001")

    assert result["ok"] is True
    assert result["msg"] == "gemini-embedding-001 — 3072d, ready to use"
