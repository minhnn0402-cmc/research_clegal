"""Thin OpenAI-compatible LLM client tuned to what the probes revealed.

Findings baked in:
  * ``cmc-legal-27`` is a Qwen-family reasoning model. For constrained tasks,
    disabling thinking (``chat_template_kwargs.enable_thinking=False``) is
    ~35x faster, ~120x cheaper, and *more* reliable (verbose reasoning blows
    the token budget and truncates before the JSON closes).
  * Responses may still wrap reasoning in ``<think>...</think>`` — strip it.
  * JSON must be recovered defensively (models add prose around it).

The client also accumulates per-call telemetry (latency, tokens) so the cost
model can extrapolate to 600k documents.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from openai import OpenAI

from experiment.config import CACHE_DIR, ModelConfig

_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL)
_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


@dataclass
class CallStats:
    """Thread-safe accumulator of call telemetry for the cost model."""

    calls: int = 0
    cache_hits: int = 0
    errors: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_s: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record(self, prompt_tokens: int, completion_tokens: int, latency_s: float) -> None:
        with self._lock:
            self.calls += 1
            self.prompt_tokens += prompt_tokens
            self.completion_tokens += completion_tokens
            self.latency_s += latency_s

    def record_cache_hit(self) -> None:
        with self._lock:
            self.cache_hits += 1

    def record_error(self) -> None:
        with self._lock:
            self.errors += 1

    def to_dict(self) -> Dict:
        with self._lock:
            total = self.calls or 1
            return {
                "calls": self.calls,
                "cache_hits": self.cache_hits,
                "errors": self.errors,
                "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens,
                "total_tokens": self.prompt_tokens + self.completion_tokens,
                "latency_s_total": round(self.latency_s, 2),
                "latency_s_mean": round(self.latency_s / total, 3),
                "completion_tokens_mean": round(self.completion_tokens / total, 1),
            }


def strip_thinking(text: str) -> str:
    """Remove ``<think>...</think>`` blocks and leading whitespace."""
    return _THINK_BLOCK.sub("", text or "").strip()


def extract_json(text: str) -> Optional[dict]:
    """Best-effort recovery of a single JSON object from a model reply."""
    cleaned = strip_thinking(text)
    # Fenced code block first.
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL)
    candidate = fence.group(1) if fence else None
    if candidate is None:
        match = _JSON_OBJECT.search(cleaned)
        candidate = match.group(0) if match else None
    if candidate is None:
        return None
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        # Trailing junk after the object is common; retry on the largest prefix.
        for end in range(len(candidate), 1, -1):
            if candidate[end - 1] != "}":
                continue
            try:
                return json.loads(candidate[:end])
            except json.JSONDecodeError:
                continue
    return None


class LlmClient:
    """One configured model, with disk cache, retry, and telemetry."""

    def __init__(
        self,
        model: ModelConfig,
        *,
        enable_thinking: bool = False,
        max_tokens: int = 1024,
        temperature: float = 0.0,
        timeout: float = 120.0,
        max_retries: int = 3,
        min_interval_s: float = 0.0,
        cache_namespace: str = "default",
    ) -> None:
        if not model.is_configured:
            raise ValueError(f"Model {model.name!r} is not configured (missing id/base_url).")
        self.model = model
        self.enable_thinking = enable_thinking and model.supports_thinking_toggle
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.max_retries = max_retries
        # Proactive client-side pacing for rate-limited endpoints (e.g. Gemini
        # free tier = 10 req/min). 0 disables throttling.
        self.min_interval_s = min_interval_s
        self._pace_lock = threading.Lock()
        self._next_allowed = 0.0
        self._client = OpenAI(base_url=model.base_url, api_key=model.api_key or "dummy", timeout=timeout)
        self.stats = CallStats()

        mode = "think" if self.enable_thinking else "nothink"
        self._cache_dir = Path(CACHE_DIR) / f"{model.name}_{mode}_{cache_namespace}"
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    def _throttle(self) -> None:
        if self.min_interval_s <= 0:
            return
        with self._pace_lock:
            now = time.time()
            wait = self._next_allowed - now
            if wait > 0:
                time.sleep(wait)
            self._next_allowed = time.time() + self.min_interval_s

    # --- caching -----------------------------------------------------------
    def _cache_key(self, messages: List[Dict]) -> str:
        payload = json.dumps(
            {"m": self.model.model_id, "t": self.enable_thinking,
             "mt": self.max_tokens, "temp": self.temperature, "msgs": messages},
            ensure_ascii=False, sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _cache_get(self, key: str) -> Optional[str]:
        path = self._cache_dir / f"{key}.json"
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))["content"]
            except (json.JSONDecodeError, KeyError, OSError):
                return None
        return None

    def _cache_put(self, key: str, content: str) -> None:
        try:
            (self._cache_dir / f"{key}.json").write_text(
                json.dumps({"content": content}, ensure_ascii=False), encoding="utf-8"
            )
        except OSError:
            pass

    # --- completion --------------------------------------------------------
    def complete(self, messages: List[Dict], *, use_cache: bool = True) -> str:
        """Return the raw assistant message content (thinking stripped)."""
        key = self._cache_key(messages)
        if use_cache:
            hit = self._cache_get(key)
            if hit is not None:
                self.stats.record_cache_hit()
                return hit

        extra_body = {}
        if self.model.supports_thinking_toggle:
            extra_body["chat_template_kwargs"] = {"enable_thinking": self.enable_thinking}

        last_exc: Optional[Exception] = None
        for attempt in range(self.max_retries):
            try:
                self._throttle()
                start = time.time()
                resp = self._client.chat.completions.create(
                    model=self.model.model_id,
                    messages=messages,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    extra_body=extra_body or None,
                )
                latency = time.time() - start
                usage = resp.usage
                self.stats.record(
                    getattr(usage, "prompt_tokens", 0) or 0,
                    getattr(usage, "completion_tokens", 0) or 0,
                    latency,
                )
                content = strip_thinking(resp.choices[0].message.content or "")
                if use_cache:
                    self._cache_put(key, content)
                return content
            except Exception as exc:  # noqa: BLE001 - surface after retries
                last_exc = exc
                # Longer backoff so a rate-limit (e.g. 429 with a ~1 min window)
                # can clear; capped at 60s.
                time.sleep(min(8 * 2 ** attempt, 60))
        self.stats.record_error()
        raise RuntimeError(f"LLM call failed after {self.max_retries} retries: {last_exc}")

    def complete_json(self, messages: List[Dict], *, use_cache: bool = True) -> Optional[dict]:
        """Completion that recovers a JSON object, or ``None`` if unparseable."""
        return extract_json(self.complete(messages, use_cache=use_cache))
