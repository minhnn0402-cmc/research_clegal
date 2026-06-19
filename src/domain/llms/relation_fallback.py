"""LangExtract-powered fallback relation extraction for ambiguous scopes."""

from __future__ import annotations

import inspect
import hashlib
import json
import os
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .prompts import langextract_prompt
from src.infrastructure.logging import get_logger


class LangExtractRelationFallback:
    """
    Run LangExtract on one clause scope and return fallback relation targets.
    """
    _base_url_env_lock = threading.Lock()

    VALID_RELATION_TYPES = {
        "dan_chieu",
        "sua_doi_bo_sung",
        "thay_the",
        "bai_bo",
        "huy_bo",
        "dinh_chi",
        "dinh_chinh",
        "huong_dan",
        "quy_dinh_chi_tiet",
        "keo_dai_hieu_luc",
        "ngung_hieu_luc",
    }

    def __init__(
        self,
        model_id: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        logger=None,
    ) -> None:
        self.logger = logger or get_logger("LangExtractRelationFallback")
        self.model_id = (
            model_id
            or os.environ.get("LEGAL_LLM_MODEL_ID")
        )
        self.base_url = (
            base_url
            or os.environ.get("LEGAL_LLM_BASE_URL")
        )
        self.api_key = (
            api_key
            or os.environ.get("LEGAL_LLM_API_KEY")

        )
        
        # Simple disk cache
        self.cache_dir = Path(".cache/legal_extraction/llm_fallback")
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def extract_relation_targets(self, content: str, clause_content: Optional[str] = None) -> List[Dict]:
        """Extract relation targets from content.

        Args:
            content: Full hierarchical context sent to the LLM for inference
                     (may include grandparent/parent/clause joined by newlines).
            clause_content: The original clause text only. When provided, positions
                            in the returned reference nodes are computed relative to
                            this string rather than the full context. This keeps
                            offsets consistent with downstream ``_build_relations``.
        """
        if not content or not content.strip():
            return []

        # Check cache
        cache_key = self._get_cache_key(content, clause_content)
        cached_result = self._get_from_cache(cache_key)
        if cached_result is not None:
            return cached_result

        annotated_document = self._run_langextract(content)
        if annotated_document is None:
            return []

        extractions = getattr(annotated_document, "extractions", None)
        if not isinstance(extractions, list):
            return []

        # `position_anchor` is the text in which we locate reference node positions.
        # Use clause_content when available so offsets match the downstream schema.
        position_anchor = clause_content if clause_content and clause_content.strip() else content

        targets: List[Dict] = []

        # Track last found position to handle multiple occurrences in sequence
        search_cursor = 0

        for extraction in extractions:
            attributes = getattr(extraction, "attributes", None) or {}
            if not isinstance(attributes, dict):
                continue

            relation_type = attributes.get("type")
            if relation_type not in self.VALID_RELATION_TYPES:
                self.logger.warning(
                    "[LLM Fallback] Skipping invalid relation type: %s", relation_type
                )
                continue

            extraction_text = str(
                getattr(extraction, "extraction_text", "") or ""
            ).strip()
            
            # Re-index the main extraction span within position_anchor
            pos_start = position_anchor.find(extraction_text, search_cursor)
            if pos_start == -1:
                pos_start = position_anchor.find(extraction_text)
            
            if pos_start != -1:
                pos_end = pos_start + len(extraction_text)
                search_cursor = pos_start + 1
            else:
                pos_start, pos_end = self._get_extraction_span(extraction)

            raw_target = attributes.get("target") or extraction_text

            # Re-derive the structured reference from `target` + search in `position_anchor`.
            # We discard the LLM's own reference dict (unreliable positions/keys).
            try:
                from .examples import _derive_reference_payload
                structured_ref = _derive_reference_payload(
                    target=raw_target,
                    context_text=position_anchor,
                )
                normalized_reference = structured_ref.get("reference") or {}
            except Exception:
                normalized_reference = {}

            targets.append({
                "relation_type": relation_type,
                "position_start": pos_start,
                "position_end": pos_end,
                "extraction_text": extraction_text,
                "target": attributes.get("target"),
                "evidence": attributes.get("evidence"),
                "reference": normalized_reference,
            })

        self.logger.debug(
            "[LLM Fallback] Extracted %d targets from %d chars of content",
            len(targets),
            len(content),
        )

        # Save to cache
        self._save_to_cache(cache_key, targets)

        return targets

    def _get_cache_key(self, content: str, clause_content: Optional[str] = None) -> str:
        """Stable key for caching LLM results, including prompt/examples fingerprint."""
        from .examples import langextract_examples
        # Fingerprint of instructions + examples
        fingerprint_data = f"prompt:{langextract_prompt}|examples_count:{len(langextract_examples)}"
        fingerprint = hashlib.md5(fingerprint_data.encode("utf-8")).hexdigest()[:8]
        
        payload = f"v2|fp:{fingerprint}|model:{self.model_id}|ctx:{content}|clause:{clause_content or ''}"
        return hashlib.md5(payload.encode("utf-8")).hexdigest()

    def _get_from_cache(self, key: str) -> Optional[List[Dict]]:
        """Retrieve result from local disk cache."""
        cache_file = self.cache_dir / f"{key}.json"
        if cache_file.exists():
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return None
        return None

    def _save_to_cache(self, key: str, result: List[Dict]):
        """Save result to local disk cache."""
        cache_file = self.cache_dir / f"{key}.json"
        try:
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False)
        except Exception:
            pass


    def _run_langextract(self, content: str):
        """
        Call LangExtract and return one ``AnnotatedDocument`` object.

        Returns ``None`` on any dependency/runtime failure so callers can
        keep deterministic extraction without interruption.
        """
        try:
            import langextract as lx
            from langextract.factory import ModelConfig
        except Exception as exc:  # pragma: no cover - optional dependency path
            self.logger.warning(
                "[LLM Fallback] langextract import failed (%s); skip fallback",
                exc,
            )
            return None

        langextract_examples = self._load_langextract_examples()
        if not langextract_examples:
            self.logger.warning(
                "[LLM Fallback] No LangExtract examples available; skip fallback"
            )
            return None

        extract_kwargs = {
            "text_or_documents": content,
            "prompt_description": langextract_prompt,
            "examples": langextract_examples,
        }

        # Force the OpenAI provider for model ID "cmc-legal"
        # No need LangExtract's built-in router patterns
        if self.base_url:
            extract_kwargs["config"] = ModelConfig(
                model_id=self.model_id,
                provider="openai",
                provider_kwargs={
                    "api_key": self.api_key,
                    "base_url": self.base_url,
                },
            )
        else:
            extract_kwargs["model_id"] = self.model_id
            if self.api_key:
                extract_kwargs["api_key"] = self.api_key

        try:
            result = lx.extract(**extract_kwargs)
        except TypeError as exc:
            # Backward-compat: older LangExtract versions may not accept "config".
            if "config" not in extract_kwargs or "config" not in str(exc):
                raise
            extract_kwargs.pop("config", None)
            extract_kwargs["model_id"] = self.model_id
            if self.api_key:
                extract_kwargs["api_key"] = self.api_key

            try:
                signature = inspect.signature(lx.extract)
            except (TypeError, ValueError):
                signature = None

            supports_base_url = False
            if signature is not None and self.base_url:
                if "base_url" in signature.parameters:
                    extract_kwargs["base_url"] = self.base_url
                    supports_base_url = True
                elif "api_base" in signature.parameters:
                    extract_kwargs["api_base"] = self.base_url
                    supports_base_url = True
                elif "openai_base_url" in signature.parameters:
                    extract_kwargs["openai_base_url"] = self.base_url
                    supports_base_url = True

            if self.base_url and not supports_base_url:
                with self._temporary_openai_base_url(self.base_url):
                    result = lx.extract(**extract_kwargs)
            else:
                result = lx.extract(**extract_kwargs)
        except Exception as exc:  # pragma: no cover - network/runtime path
            self.logger.warning(
                "[LLM Fallback] LangExtract call failed (%s); keep rule-based result",
                exc,
            )
            return None

        if isinstance(result, list):
            return result[0] if result else None
        return result

    @classmethod
    @contextmanager
    def _temporary_openai_base_url(cls, base_url: str):
        """
        Temporarily set ``OPENAI_BASE_URL`` for LangExtract/OpenAI compatibility.

        The lock avoids interleaving environment updates when multiple worker
        threads process documents at the same time.
        """
        with cls._base_url_env_lock:
            previous_value = os.environ.get("OPENAI_BASE_URL")
            os.environ["OPENAI_BASE_URL"] = base_url
            try:
                yield
            finally:
                if previous_value is None:
                    os.environ.pop("OPENAI_BASE_URL", None)
                else:
                    os.environ["OPENAI_BASE_URL"] = previous_value

    @staticmethod
    def _get_extraction_span(extraction) -> Tuple[Optional[int], Optional[int]]:
        """Best-effort extraction of ``(start, end)`` span from LangExtract payload."""
        interval = getattr(extraction, "char_interval", None)
        if interval is None:
            return None, None

        if isinstance(interval, dict):
            start_pos = interval.get("start_pos", interval.get("start"))
            end_pos = interval.get("end_pos", interval.get("end"))
            return start_pos, end_pos

        start_pos = getattr(interval, "start_pos", getattr(interval, "start", None))
        end_pos = getattr(interval, "end_pos", getattr(interval, "end", None))
        return start_pos, end_pos

    @staticmethod
    def _load_langextract_examples():
        """Load example set lazily so module import works without langextract installed."""
        try:
            from .examples import langextract_examples
        except Exception:
            return []

        return langextract_examples
