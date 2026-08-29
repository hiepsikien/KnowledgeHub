"""LLM availability defaults for Read Edition / REF relabel."""

from __future__ import annotations

import os

from .ref_schema import DEFAULT_REF_QA_MODEL


def gemini_available() -> bool:
    return bool((os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip())


def default_use_llm_relabel() -> bool:
    """Use LLM relabel when a Gemini key is configured (opt-out via env)."""
    override = (os.environ.get("KNOWLEDGEHUB_REF_LLM_DEFAULT") or "").strip().lower()
    if override in {"0", "false", "no", "off"}:
        return False
    if override in {"1", "true", "yes", "on"}:
        return gemini_available()
    return gemini_available()


def ref_llm_model() -> str:
    return DEFAULT_REF_QA_MODEL
