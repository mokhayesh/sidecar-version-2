# sidecar_llm_client.py
# Drop-in helper for Sidecar v2
# - Reads settings from defaults.json (with env overrides)
# - Injects a domain system prompt + today's date/time
# - Supports streaming responses with a cancellable handle for the Stop button

from __future__ import annotations
import os, json, threading
from dataclasses import dataclass
from typing import Iterator, Optional
from datetime import datetime, timezone

import httpx

# ──────────────────────────────────────────────────────────────────────────────
# Load defaults.json (Sidecar settings) with env var overrides
# ──────────────────────────────────────────────────────────────────────────────
DEFAULTS_PATH = os.path.join(os.path.dirname(__file__), "defaults.json")
_defaults = {}
try:
    if os.path.exists(DEFAULTS_PATH):
        with open(DEFAULTS_PATH, "r", encoding="utf-8") as f:
            _defaults = json.load(f)
except Exception:
    _defaults = {}

OPENAI_LIKE_URL = os.environ.get(
    "SIDECAR_CHAT_URL",
    _defaults.get("url", "http://127.0.0.1:8000/v1/chat/completions"),
)
OPENAI_API_KEY = os.environ.get(
    "SIDECAR_API_KEY",
    _defaults.get("api_key", "sk-aldin-local-123") or "sk-aldin-local-123",
)
DEFAULT_MODEL = os.environ.get(
    "SIDECAR_MODEL",
    _defaults.get("default_model", "aldin-mini"),
)

# ──────────────────────────────────────────────────────────────────────────────
# Domain system prompt (quick win specialization)
# You can override via env: SIDECAR_SYSTEM_PROMPT
# ──────────────────────────────────────────────────────────────────────────────
DOMAIN_SYSTEM_PROMPT = os.environ.get(
    "SIDECAR_SYSTEM_PROMPT",
    """You are **Aldin**, a specialist LLM for:
• Data Governance (policies, stewardship, lineage, controls, quality)
• Data Management (MDM, metadata, catalogs, lifecycle, retention)
• Data Architecture (conceptual/logical/physical, lakehouse, ELT/ETL)
• Analytics (BI, KPI design, experimentation, visualization)
• Data Science & MLOps (feature engineering, evaluation, drift, monitoring)

Principles:
1) Be practical and concise. Prefer checklists, tables, and concrete steps.
2) If the user is vague, ask up to 2 clarifying questions before proposing a plan.
3) Cite standards or common patterns when relevant (DAMA-DMBOK, FAIR, medallion).
4) If a request needs org-specific rules you don’t have, say so and offer a template.
5) For compare/contrast, use a 2-column table. For plans, use numbered steps.

Refuse:
- Don’t invent private policy names or internal metrics you don’t know.
- Avoid hallucinating external tool outputs; propose how to verify instead.
"""
)

def system_time_message() -> dict:
    now = datetime.now(timezone.utc).astimezone()
    return {
        "role": "system",
        "content": f"Today's date is {now.strftime('%Y-%m-%d')} and the local time is {now.strftime('%H:%M')} {now.tzname()}."
    }

def domain_prompt_message() -> dict:
    return {"role": "system", "content": DOMAIN_SYSTEM_PROMPT}

def with_injected_system(messages: list[dict]) -> list[dict]:
    """Ensure our 2 system messages are first: (1) domain prompt, (2) date/time."""
    msgs = messages or []
    # Remove any previous auto-injected versions to avoid duplication
    def is_auto_system(m: dict) -> bool:
        if m.get("role") != "system":
            return False
        c = (m.get("content") or "").strip()
        return ("Aldin, a specialist LLM" in c) or c.startswith("Today's date is ")
    msgs = [m for m in msgs if not is_auto_system(m)]
    # Prepend our system messages
    return [domain_prompt_message(), system_time_message(), *msgs]

# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────
@dataclass
class ChatSettings:
    model: str = DEFAULT_MODEL
    temperature: float = float(_defaults.get("temperature", "0.6"))
    top_p: float = float(_defaults.get("top_p", "1.0"))
    max_tokens: int = int(_defaults.get("max_tokens", "800"))
    stream: bool = True
    timeout: float = 120.0

class StreamHandle:
    """Holds state for an in-flight stream so the UI can cancel it."""
    def __init__(self):
        self._cancel = threading.Event()
        self._resp: Optional[httpx.Response] = None

    def attach(self, resp: httpx.Response) -> None:
        self._resp = resp

    def cancel(self) -> None:
        self._cancel.set()
        try:
            if self._resp is not None:
                self._resp.close()  # closes the socket → server stops streaming
        except Exception:
            pass

    @property
    def is_cancelled(self) -> bool:
        return self._cancel.is_set()

def stream_chat(messages: list[dict], settings: ChatSettings, handle: StreamHandle) -> Iterator[str]:
    """Yield text deltas; call handle.cancel() from the UI's Stop button."""
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.model,
        "messages": with_injected_system(messages),
        "temperature": settings.temperature,
        "top_p": settings.top_p,
        "max_tokens": settings.max_tokens,
        "stream": True,
    }
    with httpx.Client(timeout=settings.timeout) as client:
        with client.stream("POST", OPENAI_LIKE_URL, headers=headers, json=payload) as resp:
            handle.attach(resp)
            resp.raise_for_status()
            for line in resp.iter_lines():
                if handle.is_cancelled:
                    break
                if not line or not line.startswith("data:"):
                    continue
                data = line.removeprefix("data:").strip()
                if data == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                    delta = obj["choices"][0]["delta"].get("content")
                    if delta:
                        yield delta
                except Exception:
                    continue

def complete_once(messages: list[dict], settings: ChatSettings) -> str:
    """Non-streaming call that returns a full completion string."""
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.model,
        "messages": with_injected_system(messages),
        "temperature": settings.temperature,
        "top_p": settings.top_p,
        "max_tokens": settings.max_tokens,
        "stream": False,
    }
    with httpx.Client(timeout=settings.timeout) as client:
        r = client.post(OPENAI_LIKE_URL, headers=headers, json=payload)
        r.raise_for_status()
        obj = r.json()
        return obj["choices"][0]["message"]["content"]
