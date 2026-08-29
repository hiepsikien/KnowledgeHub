from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _disable_ref_llm_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KNOWLEDGEHUB_REF_LLM_DEFAULT", "0")
