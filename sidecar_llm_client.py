"""
sidecar_llm_client.py
A tiny client for your Aldin-Mini local API (OpenAI-compatible Chat Completions).

Usage:
    from sidecar_llm_client import LocalLLMClient
    client = LocalLLMClient(
        base_url="http://127.0.0.1:8000/v1/chat/completions",
        api_key="sk-aldin-local-123",
        model="aldin-mini"
    )
    text = client.chat_once([{"role":"user","content":"Hello!"}])
    for token in client.chat_stream([{"role":"user","content":"Stream please"}]): print(token, end="")
"""
from __future__ import annotations
import json
import requests
from typing import Dict, List, Iterable, Optional

DEFAULT_TIMEOUT_S = 120

def _headers(api_key: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}" if api_key else "",
        "Content-Type": "application/json",
    }

class LocalLLMClient:
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8000/v1/chat/completions",
        api_key: str = "",
        model: str = "aldin-mini",
        timeout: int = DEFAULT_TIMEOUT_S,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = int(timeout)

    # -------------------- non-streamed --------------------
    def chat_once(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 256,
        extra: Optional[Dict] = None,
    ) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": float(temperature),
            "max_tokens": int(max_tokens),
        }
        if extra:
            payload.update(extra)
        r = requests.post(
            self.base_url,
            headers=_headers(self.api_key),
            data=json.dumps(payload),
            timeout=self.timeout,
        )
        r.raise_for_status()
        data = r.json()
        return data["choices"][0]["message"]["content"]

    # -------------------- streaming --------------------
    def chat_stream(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 256,
        extra: Optional[Dict] = None,
    ) -> Iterable[str]:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": float(temperature),
            "max_tokens": int(max_tokens),
            "stream": True,
        }
        if extra:
            payload.update(extra)
        with requests.post(
            self.base_url,
            headers=_headers(self.api_key),
            data=json.dumps(payload),
            stream=True,
            timeout=self.timeout,
        ) as r:
            r.raise_for_status()
            for raw in r.iter_lines(decode_unicode=True):
                if not raw or not raw.startswith("data: "):
                    continue
                chunk = raw[6:]
                if chunk == "[DONE]":
                    break
                obj = json.loads(chunk)
                delta = obj["choices"][0]["delta"].get("content", "")
                if delta:
                    yield delta

# --------------- convenience helpers using your defaults dict ---------------
def client_from_defaults(defaults: Dict) -> LocalLLMClient:
    """
    Create a client directly from your Sidecar defaults dict.
    Expects:
      defaults["url"]            -> "http://127.0.0.1:8000/v1/chat/completions"
      defaults["api_key"]        -> "sk-..."
      defaults["default_model"]  -> "aldin-mini"
    """
    base_url = defaults.get("url", "http://127.0.0.1:8000/v1/chat/completions")
    api_key = defaults.get("api_key", "")
    model = defaults.get("default_model", "aldin-mini")
    return LocalLLMClient(base_url=base_url, api_key=api_key, model=model)

def chat_once_with_defaults(defaults: Dict, user_text: str, system_text: str = "You are a helpful data-governance assistant.") -> str:
    client = client_from_defaults(defaults)
    messages = [
        {"role": "system", "content": system_text},
        {"role": "user", "content": user_text},
    ]
    temp = float(defaults.get("temperature", "0.7"))
    max_toks = int(defaults.get("max_tokens", "256"))
    return client.chat_once(messages, temperature=temp, max_tokens=max_toks)

def chat_stream_with_defaults(defaults: Dict, user_text: str, system_text: str = "You are a helpful data-governance assistant.") -> Iterable[str]:
    client = client_from_defaults(defaults)
    messages = [
        {"role": "system", "content": system_text},
        {"role": "user", "content": user_text},
    ]
    temp = float(defaults.get("temperature", "0.7"))
    max_toks = int(defaults.get("max_tokens", "256"))
    return client.chat_stream(messages, temperature=temp, max_tokens=max_toks)

