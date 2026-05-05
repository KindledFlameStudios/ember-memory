"""Embedding provider model discovery and verification helpers.

The controller uses this module to populate cloud model pickers without
coupling UI code to each provider's API shape. Live provider responses are
normalised to the same ``{id, name, description}`` dictionaries used by the UI.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request

from ember_memory.core.embeddings.google_provider import _MODEL_DIMS as GOOGLE_MODEL_DIMS
from ember_memory.core.embeddings.openai_provider import _MODEL_DIMS as OPENAI_MODEL_DIMS
from ember_memory.core.embeddings.openrouter_provider import _MODEL_DIMS as OPENROUTER_MODEL_DIMS


OPENAI_MODELS_URL = "https://api.openai.com/v1/models"
GOOGLE_MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models"
OPENROUTER_EMBEDDING_MODELS_URL = "https://openrouter.ai/api/v1/embeddings/models"
OPENROUTER_MODELS_FALLBACK_URL = "https://openrouter.ai/api/v1/models?output_modalities=embeddings"

PREFERRED_MODEL_ORDER = {
    "openai": ["text-embedding-3-small", "text-embedding-3-large", "text-embedding-ada-002"],
    "google": ["gemini-embedding-001", "gemini-embedding-2-preview"],
    "openrouter": ["baai/bge-m3"],
}


def friendly_auth_error(msg: str) -> str:
    """Convert raw HTTP/API errors into user-facing controller messages."""
    low = str(msg).lower()
    if "401" in low or "unauthorized" in low or "invalid" in low:
        return "Invalid API key"
    if "403" in low or "forbidden" in low:
        return "API key lacks permissions"
    if "429" in low or "rate limit" in low or "too many" in low:
        return "Rate limited; try again in a moment"
    if "timeout" in low or "timed out" in low:
        return "Connection timed out"
    if "connection" in low and ("refused" in low or "reset" in low):
        return "Connection refused; check network"
    text = str(msg)
    return text.split(":")[-1].strip() if ":" in text else text[:80]


def _read_json(req: urllib.request.Request, timeout: int = 10) -> dict:
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def _known_models(model_dims: dict[str, int], *, provider: str = "", msg: str = "") -> dict:
    models = [
        {
            "id": model_id,
            "name": model_id,
            "description": f"{dim}d embedding vector",
            "free": False,
        }
        for model_id, dim in model_dims.items()
    ]
    _sort_models(models, provider)
    result = {"ok": True, "models": models, "live": False}
    if msg:
        result["msg"] = msg
    return result


def _sort_models(models: list[dict], provider: str = "") -> None:
    preferred = PREFERRED_MODEL_ORDER.get(provider, [])
    preferred_index = {model_id: i for i, model_id in enumerate(preferred)}
    models.sort(key=lambda item: (preferred_index.get(item["id"], len(preferred)), item["id"]))


def known_openai_models(msg: str = "") -> dict:
    return _known_models(OPENAI_MODEL_DIMS, provider="openai", msg=msg)


def known_google_models(msg: str = "") -> dict:
    return _known_models(GOOGLE_MODEL_DIMS, provider="google", msg=msg)


def known_openrouter_models(msg: str = "") -> dict:
    return _known_models(OPENROUTER_MODEL_DIMS, provider="openrouter", msg=msg)


def _google_model_id(name: str) -> str:
    """Convert Gemini API resource names to provider constructor IDs."""
    return str(name or "").removeprefix("models/")


def _is_google_embedding_model(model: dict) -> bool:
    methods = model.get("supportedGenerationMethods") or model.get("supportedActions") or []
    if "embedContent" in methods:
        return True
    name = str(model.get("name", "")).lower()
    display = str(model.get("displayName", "")).lower()
    return "embedding" in name or "embedding" in display or "embed" in name


def fetch_openai_models(api_key: str) -> dict:
    """Fetch OpenAI embedding models using the Models API."""
    if not api_key:
        return known_openai_models("OpenAI API key not configured; showing built-in models")

    try:
        req = urllib.request.Request(
            OPENAI_MODELS_URL,
            headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
            method="GET",
        )
        data = _read_json(req)
    except Exception as exc:
        return known_openai_models(f"Could not refresh OpenAI models: {friendly_auth_error(str(exc))}")

    models = []
    for model in data.get("data", []):
        model_id = str(model.get("id", ""))
        if not model_id.startswith("text-embedding"):
            continue
        dim = OPENAI_MODEL_DIMS.get(model_id)
        description = f"{dim}d embedding vector" if dim else "embedding model"
        models.append({
            "id": model_id,
            "name": model_id,
            "description": description,
            "free": False,
        })
    _sort_models(models, "openai")

    if not models:
        return known_openai_models("OpenAI returned no embedding models; showing built-in models")
    return {"ok": True, "models": models, "live": True}


def fetch_google_models(api_key: str) -> dict:
    """Fetch Gemini embedding models and normalise resource names to bare IDs."""
    if not api_key:
        return known_google_models("Google API key not configured; showing built-in models")

    try:
        url = GOOGLE_MODELS_URL + "?" + urllib.parse.urlencode({"key": api_key, "pageSize": "1000"})
        req = urllib.request.Request(url, method="GET")
        data = _read_json(req)
    except Exception as exc:
        return known_google_models(f"Could not refresh Google models: {friendly_auth_error(str(exc))}")

    models = []
    for model in data.get("models", []):
        if not _is_google_embedding_model(model):
            continue
        model_id = _google_model_id(model.get("name", ""))
        if not model_id:
            continue
        dim = GOOGLE_MODEL_DIMS.get(model_id)
        description = model.get("description") or (f"{dim}d embedding vector" if dim else "embedding model")
        models.append({
            "id": model_id,
            "name": model.get("displayName") or model_id,
            "description": description,
            "free": False,
        })
    _sort_models(models, "google")

    if not models:
        return known_google_models("Google returned no embedding models; showing built-in models")
    return {"ok": True, "models": models, "live": True}


def fetch_openrouter_models(api_key: str) -> dict:
    """Fetch OpenRouter embedding models from the embeddings model endpoint."""
    if not api_key:
        return known_openrouter_models("OpenRouter API key not configured; showing built-in models")

    last_error = ""
    try:
        req = urllib.request.Request(
            OPENROUTER_EMBEDDING_MODELS_URL,
            headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
            method="GET",
        )
        data = _read_json(req)
    except Exception as exc:
        last_error = friendly_auth_error(str(exc))
        try:
            req = urllib.request.Request(
                OPENROUTER_MODELS_FALLBACK_URL,
                headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
                method="GET",
            )
            data = _read_json(req)
        except Exception as fallback_exc:
            msg = friendly_auth_error(str(fallback_exc)) or last_error
            return known_openrouter_models(f"Could not refresh OpenRouter models: {msg}")

    models = []
    for model in data.get("data", []):
        model_id = str(model.get("id", ""))
        if not model_id:
            continue
        dim = OPENROUTER_MODEL_DIMS.get(model_id)
        description = model.get("description") or (f"{dim}d embedding vector" if dim else "embedding model")
        models.append({
            "id": model_id,
            "name": model.get("name") or model_id,
            "description": description,
            "free": str(model_id).endswith(":free"),
        })
    _sort_models(models, "openrouter")

    if not models:
        return known_openrouter_models("OpenRouter returned no embedding models; showing built-in models")
    return {"ok": True, "models": models, "live": True}


def get_provider_models(provider: str, api_key: str = "") -> dict:
    provider = str(provider or "").lower().strip()
    if provider == "openai":
        return fetch_openai_models(api_key)
    if provider == "google":
        return fetch_google_models(api_key)
    if provider == "openrouter":
        return fetch_openrouter_models(api_key)
    return {"ok": False, "msg": f"Unknown provider: {provider}", "models": []}


def verify_provider_auth(provider: str, api_key: str) -> dict:
    """Check whether a provider key can reach the provider's model endpoint."""
    provider = str(provider or "").lower().strip()
    api_key = str(api_key or "").strip()
    if not api_key:
        return {"ok": False, "msg": "No API key provided"}

    result = get_provider_models(provider, api_key)
    if result.get("live"):
        count = len(result.get("models", []))
        return {"ok": True, "msg": f"Connected; {count} embedding models available"}

    msg = result.get("msg", "Could not verify provider")
    return {"ok": False, "msg": friendly_auth_error(msg)}


def verify_model(provider: str, model: str) -> dict:
    """Validate model shape against known dimensions without making network calls."""
    provider = str(provider or "").lower().strip()
    model = _google_model_id(str(model or "").strip()) if provider == "google" else str(model or "").strip()
    if not model:
        return {"ok": False, "msg": "No model specified"}

    dims_by_provider = {
        "openai": OPENAI_MODEL_DIMS,
        "google": GOOGLE_MODEL_DIMS,
        "openrouter": OPENROUTER_MODEL_DIMS,
    }
    dims = dims_by_provider.get(provider)
    if dims is None:
        return {"ok": False, "msg": f"Unknown provider: {provider}"}
    if model in dims:
        return {"ok": True, "msg": f"{model} — {dims[model]}d, ready to use"}
    return {"ok": True, "msg": f"{model} — dimension unknown; save only if this model supports embeddings"}
