# sidecar_llm_client.py
from __future__ import annotations

import json
import time
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Generator, Iterable, List, Optional

import requests
from zoneinfo import ZoneInfo

# ──────────────────────────────────────────────────────────────────────────────
# Config & defaults
# ──────────────────────────────────────────────────────────────────────────────

DEFAULTS_FILE = "defaults.json"

def _load_defaults() -> Dict:
    try:
        return json.load(open(DEFAULTS_FILE, "r", encoding="utf-8"))
    except Exception:
        return {}

DEFAULTS = _load_defaults()

# ──────────────────────────────────────────────────────────────────────────────
# Domain system prompt (with {{TODAY}} injection)
# ──────────────────────────────────────────────────────────────────────────────

DOMAIN_SYSTEM_PROMPT = """You are Aldin-Mini, a domain assistant for:
• Data Governance (policies, lineage, stewardship, controls)
• Data Management (MDM, metadata, cataloging, lifecycle)
• Data Architecture (patterns, lakehouse/mesh/warehouse, modeling)
• Analytics & BI, and Data Science/ML

Ground your answers in practical, auditable steps (policies → controls → roles → artifacts).
Prefer bullet points, numbered steps, and examples. When asked for “today’s” info, use the injected date: {{TODAY}}.
If content feels generic, ask one clarifying question before answering.
"""

def _today_str() -> str:
    # Use your local timezone so “today” is correct in your UI
    tz = ZoneInfo("America/Detroit")
    return datetime.now(tz).date().isoformat()

def _inject_domain_prompt(messages: List[Dict]) -> List[Dict]:
    """Ensure a system message is first; inject TODAY into the prompt."""
    sys = DOMAIN_SYSTEM_PROMPT.replace("{{TODAY}}", _today_str())
    has_system = len(messages) > 0 and messages[0].get("role") == "system"

    if has_system:
        # Keep existing system content, append our domain brain under a divider
        merged = messages[0]["content"].rstrip() + "\n\n---\n" + sys
        out = [{"role": "system", "content": merged}]
        out.extend(messages[1:])
        return out
    else:
        return [{"role": "system", "content": sys}, *messages]

# ──────────────────────────────────────────────────────────────────────────────
# Settings & Provider plumbing
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class ChatSettings:
    provider: str = DEFAULTS.get("provider", "custom")  # custom | openai | gemini | auto
    url: str = DEFAULTS.get("url", "http://127.0.0.1:8000/v1/chat/completions")
    api_key: str = DEFAULTS.get("api_key", "")
    org: str = DEFAULTS.get("openai_org", "")

    default_model: str = DEFAULTS.get("default_model", "aldin-mini")
    temperature: float = float(DEFAULTS.get("temperature", "0.6"))
    top_p: float = float(DEFAULTS.get("top_p", "1.0"))
    max_tokens: int = int(DEFAULTS.get("max_tokens", "800"))

    # Stored profiles so you can switch providers without retyping
    custom_url: str = DEFAULTS.get("custom_url", "http://127.0.0.1:8000/v1/chat/completions")
    custom_api_key: str = DEFAULTS.get("custom_api_key", "sk-aldin-local-123")
    custom_model: str = DEFAULTS.get("custom_model", "aldin-mini")

    openai_url: str = DEFAULTS.get("openai_url", "https://api.openai.com/v1/chat/completions")
    openai_api_key: str = DEFAULTS.get("openai_api_key", "")
    openai_default_model: str = DEFAULTS.get("openai_default_model", "gpt-4o")

    gemini_text_url: str = DEFAULTS.get("gemini_text_url", "https://generativelanguage.googleapis.com/v1beta/models")
    gemini_api_key: str = DEFAULTS.get("gemini_api_key", "")
    gemini_default_model: str = DEFAULTS.get("gemini_default_model", "gemini-1.5-pro")

    def resolve(self) -> "ChatSettings":
        """Return a copy with URL/API/model switched based on provider."""
        s = ChatSettings(**self.__dict__)
        p = (self.provider or "custom").lower()

        if p in ("custom", "auto"):
            s.url = self.custom_url or s.url
            s.api_key = self.custom_api_key or s.api_key
            s.default_model = self.custom_model or s.default_model
        elif p == "openai":
            s.url = self.openai_url or s.url
            s.api_key = self.openai_api_key or s.api_key
            s.default_model = self.openai_default_model or s.default_model
        elif p == "gemini":
            # Gemini uses a different REST shape (we handle below)
            s.api_key = self.gemini_api_key or s.api_key
            s.default_model = self.gemini_default_model or s.default_model
        return s

# For the Stop button
class StreamHandle:
    def __init__(self) -> None:
        self._cancel = False
        self._lock = threading.Lock()

    def cancel(self) -> None:
        with self._lock:
            self._cancel = True

    def cancelled(self) -> bool:
        with self._lock:
            return self._cancel

# ──────────────────────────────────────────────────────────────────────────────
# Core APIs
# ──────────────────────────────────────────────────────────────────────────────

def _headers(settings: ChatSettings) -> Dict[str, str]:
    h = {"Content-Type": "application/json"}
    if settings.api_key:
        h["Authorization"] = f"Bearer {settings.api_key}"
    if settings.org:
        h["OpenAI-Organization"] = settings.org
    return h

def complete_once(
    messages: List[Dict],
    settings: Optional[ChatSettings] = None,
    model: Optional[str] = None,
) -> str:
    """Non-streaming completion; returns the assistant text."""
    settings = (settings or ChatSettings()).resolve()
    msgs = _inject_domain_prompt(messages)

    if settings.provider == "gemini":
        # Gemini: POST {base}/{model}:generateContent?key=API_KEY
        url = f"{settings.gemini_text_url}/{model or settings.default_model}:generateContent?key={settings.api_key}"
        # Convert messages → Gemini format
        parts = []
        for m in msgs:
            role = "user" if m["role"] in ("user", "system") else "model"
            parts.append({"role": role, "parts": [{"text": m["content"]}]})
        payload = {
            "contents": parts,
            "generationConfig": {
                "temperature": settings.temperature,
                "topP": settings.top_p,
                "maxOutputTokens": settings.max_tokens,
            },
        }
        r = requests.post(url, json=payload, timeout=600)
        r.raise_for_status()
        data = r.json()
        try:
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except Exception:
            return json.dumps(data, indent=2)

    # OpenAI-compatible (OpenAI or your local llama.cpp server)
    url = settings.url
    payload = {
        "model": model or settings.default_model,
        "messages": msgs,
        "temperature": settings.temperature,
        "top_p": settings.top_p,
        "max_tokens": settings.max_tokens,
    }
    r = requests.post(url, headers=_headers(settings), json=payload, timeout=600)
    r.raise_for_status()
    data = r.json()
    try:
        return data["choices"][0]["message"]["content"]
    except Exception:
        return json.dumps(data, indent=2)

def stream_chat(
    messages: List[Dict],
    settings: Optional[ChatSettings] = None,
    handle: Optional[StreamHandle] = None,
    model: Optional[str] = None,
) -> Iterable[str]:
    """Streaming generator of text deltas; yields str chunks as they arrive."""
    settings = (settings or ChatSettings()).resolve()
    handle = handle or StreamHandle()
    msgs = _inject_domain_prompt(messages)

    if settings.provider == "gemini":
        # Simple "poor man's" stream: poll once, then yield chunks
        text = complete_once(messages, settings=settings, model=model)
        for ch in _chunk(text, 32):
            if handle.cancelled():
                break
            yield ch
            time.sleep(0.005)
        return

    # OpenAI-compatible streaming
    url = settings.url
    payload = {
        "model": model or settings.default_model,
        "messages": msgs,
        "temperature": settings.temperature,
        "top_p": settings.top_p,
        "max_tokens": settings.max_tokens,
        "stream": True,
    }

    with requests.post(url, headers=_headers(settings), json=payload, stream=True, timeout=600) as r:
        r.raise_for_status()
        for line in r.iter_lines(decode_unicode=True):
            if handle.cancelled():
                break
            if not line:
                continue
            if line.startswith("data: "):
                data = line[6:].strip()
                if data == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                    delta = obj["choices"][0]["delta"].get("content", "")
                    if delta:
                        yield delta
                except Exception:
                    # If the server sends non-JSON lines, ignore them
                    continue

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _chunk(s: str, n: int) -> Generator[str, None, None]:
    for i in range(0, len(s), n):
        yield s[i:i+n]
