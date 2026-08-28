from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from knowledgehub.translation.draft import draft_chapter, draft_sample
from knowledgehub.translation.project import init_translation_project, select_translation_mode
from knowledgehub.translation.providers import ProviderError, deepseek_chat, gemini_generate


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    catalog = tmp_path / "catalog"
    catalog.mkdir()
    sources = tmp_path / "sources/grotius/raw"
    sources.mkdir(parents=True)
    (sources / "freedom_of_the_seas.txt").write_text(
        "CHAPTER I\n\nEnglish paragraph one.\n\nCHAPTER II\n\nEnglish paragraph two.\n",
        encoding="utf-8",
    )
    works = [
        {
            "id": "grotius--freedom_of_the_seas",
            "title": "The Freedom of the Seas",
            "author_id": "grotius",
            "language": "en",
            "content_file": "sources/grotius/raw/freedom_of_the_seas.txt",
        }
    ]
    (catalog / "works.json").write_text(json.dumps(works), encoding="utf-8")
    (catalog / "authors.json").write_text(json.dumps([{"id": "grotius", "name": "Grotius"}]), encoding="utf-8")
    monkeypatch.setenv("KNOWLEDGEHUB_CORPUS", str(tmp_path))
    return tmp_path


def test_deepseek_missing_key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(ProviderError, match="DEEPSEEK_API_KEY"):
        deepseek_chat([{"role": "user", "content": "hi"}])


def test_gemini_sends_key_in_header(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GEMINI_API_KEY", "secret-key")
    captured: dict = {}

    def fake_post(url, headers, payload, *, timeout=300):
        captured["url"] = url
        captured["headers"] = headers
        captured["payload"] = payload
        return {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}

    monkeypatch.setattr("knowledgehub.translation.providers._post_json", fake_post)
    assert gemini_generate("hi") == "ok"
    assert "key=" not in captured["url"]
    assert captured["headers"]["x-goog-api-key"] == "secret-key"
    assert captured["payload"]["generationConfig"]["maxOutputTokens"] == 65536


def test_deepseek_sets_max_tokens_and_rejects_length(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    captured: dict = {}

    def fake_post(url, headers, payload, *, timeout=300):
        captured["payload"] = payload
        return {
            "choices": [
                {
                    "finish_reason": "length",
                    "message": {"content": "Bản dịch bị cắt giữa câu và thiếu phầ"},
                }
            ]
        }

    monkeypatch.setattr("knowledgehub.translation.providers._post_json", fake_post)
    with pytest.raises(ProviderError, match="finish_reason=length"):
        deepseek_chat([{"role": "user", "content": "hi"}])
    assert captured["payload"]["max_tokens"] == 65536


def test_draft_sample_writes_normal(corpus: Path):
    init_translation_project("grotius--freedom_of_the_seas")
    with (
        patch("knowledgehub.translation.draft.complete_chat", return_value="Bản dịch thô."),
        patch("knowledgehub.translation.draft.complete_prompt", return_value="Bản dịch đã chỉnh."),
    ):
        result = draft_sample("grotius--freedom_of_the_seas", mode="normal")
    assert result["mode"] == "normal"
    sample = corpus / "translations/grotius--freedom_of_the_seas/segments/chi-sample.json"
    payload = json.loads(sample.read_text(encoding="utf-8"))
    assert payload["drafts"]["normal"] == "Bản dịch đã chỉnh."
    assert payload["draft_raw"]["normal"] == "Bản dịch thô."
    assert payload["final"] == "Bản dịch đã chỉnh."
    project = json.loads((corpus / "translations/grotius--freedom_of_the_seas/project.json").read_text())
    assert project["translation_mode"] is None
    assert project["status"] == "sample_ready"


def test_draft_chapter_requires_locked_mode(corpus: Path):
    init_translation_project("grotius--freedom_of_the_seas")
    with pytest.raises(ValueError, match="translation_mode not locked"):
        draft_chapter("grotius--freedom_of_the_seas", chapter="II")


def test_draft_chapter_writes_locked_mode(corpus: Path):
    init_translation_project("grotius--freedom_of_the_seas")
    sample = corpus / "translations/grotius--freedom_of_the_seas/segments/chi-sample.json"
    payload = json.loads(sample.read_text(encoding="utf-8"))
    payload["drafts"]["tight"] = "Bản dịch tight."
    sample.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    select_translation_mode("grotius--freedom_of_the_seas", "tight")
    with (
        patch("knowledgehub.translation.draft.complete_chat", return_value="Chương II thô."),
        patch("knowledgehub.translation.draft.complete_prompt", return_value="Chương II đã chỉnh."),
    ):
        result = draft_chapter("grotius--freedom_of_the_seas", chapter="II")
    assert result["mode"] == "tight"
    chii = json.loads(
        (corpus / "translations/grotius--freedom_of_the_seas/segments/chii.json").read_text(encoding="utf-8")
    )
    assert chii["drafts"]["tight"] == "Chương II đã chỉnh."
    assert chii["final"] == "Chương II đã chỉnh."
    assert chii["status"] == "draft_ready"
    assert chii["pipeline"]["polish_pending"] is False
    assert result["reused_draft"] is False


def test_draft_chapter_checkpoints_raw_if_polish_fails(corpus: Path):
    init_translation_project("grotius--freedom_of_the_seas")
    sample = corpus / "translations/grotius--freedom_of_the_seas/segments/chi-sample.json"
    payload = json.loads(sample.read_text(encoding="utf-8"))
    payload["drafts"]["tight"] = "Bản dịch tight."
    sample.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    select_translation_mode("grotius--freedom_of_the_seas", "tight")
    with (
        patch("knowledgehub.translation.draft.complete_chat", return_value="Chương II thô.") as mock_chat,
        patch(
            "knowledgehub.translation.draft.complete_prompt",
            side_effect=ProviderError("HTTP 503: high demand"),
        ),
    ):
        with pytest.raises(ProviderError, match="503"):
            draft_chapter("grotius--freedom_of_the_seas", chapter="II")
    mock_chat.assert_called_once()
    chii = json.loads(
        (corpus / "translations/grotius--freedom_of_the_seas/segments/chii.json").read_text(encoding="utf-8")
    )
    assert chii["draft_raw"]["tight"] == "Chương II thô."
    assert not str(chii.get("final") or "").strip()
    assert chii["pipeline"]["polish_pending"] is True
    assert chii["status"] == "pending"

    with (
        patch("knowledgehub.translation.draft.complete_chat") as mock_chat_again,
        patch("knowledgehub.translation.draft.complete_prompt", return_value="Chương II đã chỉnh.") as mock_polish,
    ):
        result = draft_chapter("grotius--freedom_of_the_seas", chapter="II")
    mock_chat_again.assert_not_called()
    mock_polish.assert_called_once()
    assert result["reused_draft"] is True
    chii = json.loads(
        (corpus / "translations/grotius--freedom_of_the_seas/segments/chii.json").read_text(encoding="utf-8")
    )
    assert chii["final"] == "Chương II đã chỉnh."
    assert chii["draft_raw"]["tight"] == "Chương II thô."
    assert chii["pipeline"]["polish_pending"] is False


def test_draft_chapter_force_draft_reruns_deepseek(corpus: Path):
    init_translation_project("grotius--freedom_of_the_seas")
    sample = corpus / "translations/grotius--freedom_of_the_seas/segments/chi-sample.json"
    payload = json.loads(sample.read_text(encoding="utf-8"))
    payload["drafts"]["tight"] = "Bản dịch tight."
    sample.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    select_translation_mode("grotius--freedom_of_the_seas", "tight")
    chii_path = corpus / "translations/grotius--freedom_of_the_seas/segments/chii.json"
    chii = json.loads(chii_path.read_text(encoding="utf-8"))
    chii["draft_raw"] = {"tight": "Nháp cũ."}
    chii["pipeline"] = {"polish_pending": True}
    chii_path.write_text(json.dumps(chii, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with (
        patch("knowledgehub.translation.draft.complete_chat", return_value="Nháp mới.") as mock_chat,
        patch("knowledgehub.translation.draft.complete_prompt", return_value="Đã chỉnh."),
    ):
        result = draft_chapter("grotius--freedom_of_the_seas", chapter="II", force_draft=True)
    mock_chat.assert_called_once()
    assert result["reused_draft"] is False
    chii = json.loads(chii_path.read_text(encoding="utf-8"))
    assert chii["draft_raw"]["tight"] == "Nháp mới."
    assert chii["final"] == "Đã chỉnh."


def test_looks_cut_off():
    from knowledgehub.translation.draft import looks_cut_off

    assert looks_cut_off("Ngược lại, nếu họ đã đặt trọng tâm vào sự thật r") is True
    assert looks_cut_off("Navigation on the sea is open to any one.") is False
    assert looks_cut_off("short") is False


def test_draft_chapter_rejects_truncated_deepseek(corpus: Path):
    init_translation_project("grotius--freedom_of_the_seas")
    sample = corpus / "translations/grotius--freedom_of_the_seas/segments/chi-sample.json"
    payload = json.loads(sample.read_text(encoding="utf-8"))
    payload["drafts"]["tight"] = "Bản dịch tight."
    sample.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    select_translation_mode("grotius--freedom_of_the_seas", "tight")
    cut = "Đây là một bản dịch dài đủ hai mươi ký tự nhưng bị cắt giữa chừ"
    with (
        patch("knowledgehub.translation.draft.complete_chat", return_value=cut),
        patch("knowledgehub.translation.draft.complete_prompt") as mock_polish,
    ):
        with pytest.raises(ProviderError, match="truncated"):
            draft_chapter("grotius--freedom_of_the_seas", chapter="II")
    mock_polish.assert_not_called()
    chii = json.loads(
        (corpus / "translations/grotius--freedom_of_the_seas/segments/chii.json").read_text(encoding="utf-8")
    )
    assert not str((chii.get("draft_raw") or {}).get("tight") or "").strip()
    assert not str(chii.get("final") or "").strip()


def test_draft_does_not_reuse_truncated_raw(corpus: Path):
    init_translation_project("grotius--freedom_of_the_seas")
    sample = corpus / "translations/grotius--freedom_of_the_seas/segments/chi-sample.json"
    payload = json.loads(sample.read_text(encoding="utf-8"))
    payload["drafts"]["tight"] = "Bản dịch tight."
    sample.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    select_translation_mode("grotius--freedom_of_the_seas", "tight")
    chii_path = corpus / "translations/grotius--freedom_of_the_seas/segments/chii.json"
    chii = json.loads(chii_path.read_text(encoding="utf-8"))
    chii["draft_raw"] = {"tight": "Nháp cũ bị cắt giữa câu và thiếu phần còn lại r"}
    chii["pipeline"] = {"polish_pending": True}
    chii_path.write_text(json.dumps(chii, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with (
        patch("knowledgehub.translation.draft.complete_chat", return_value="Nháp mới đủ câu.") as mock_chat,
        patch("knowledgehub.translation.draft.complete_prompt", return_value="Đã chỉnh đủ câu."),
    ):
        result = draft_chapter("grotius--freedom_of_the_seas", chapter="II")
    mock_chat.assert_called_once()
    assert result["reused_draft"] is False
    chii = json.loads(chii_path.read_text(encoding="utf-8"))
    assert chii["draft_raw"]["tight"] == "Nháp mới đủ câu."
    assert chii["final"] == "Đã chỉnh đủ câu."


def test_draft_chapter_translates_each_part(corpus: Path):
    init_translation_project("grotius--freedom_of_the_seas")
    sample = corpus / "translations/grotius--freedom_of_the_seas/segments/chi-sample.json"
    payload = json.loads(sample.read_text(encoding="utf-8"))
    payload["drafts"]["tight"] = "Bản dịch tight."
    sample.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    select_translation_mode("grotius--freedom_of_the_seas", "tight")
    chii_path = corpus / "translations/grotius--freedom_of_the_seas/segments/chii.json"
    chii = json.loads(chii_path.read_text(encoding="utf-8"))
    paras = [" ".join(["alpha", str(i)] + ["word"] * 25) for i in range(8)]
    chii["source_text"] = "\n\n".join(paras)
    from knowledgehub.translation.segment import chapter_word_count

    chii["words"] = chapter_word_count(chii["source_text"])
    chii_path.write_text(json.dumps(chii, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    calls: list = []

    def fake_chat(messages, **_kwargs):
        calls.append(messages)
        return f"Bản dịch phần số {len(calls)} được viết thành một câu hoàn chỉnh."

    def fake_polish(*_args, **_kwargs):
        return f"Bản chỉnh phần số {len(calls)} được viết thành một câu hoàn chỉnh."

    with (
        patch("knowledgehub.translation.draft.part_limits", return_value=(40, 70)),
        patch("knowledgehub.translation.draft.complete_chat", side_effect=fake_chat),
        patch("knowledgehub.translation.draft.complete_prompt", side_effect=fake_polish),
    ):
        result = draft_chapter("grotius--freedom_of_the_seas", chapter="II")
    assert len(calls) > 1
    chii = json.loads(chii_path.read_text(encoding="utf-8"))
    assert len(chii["parts"]) == len(calls)
    assert result["reused_draft"] is False
    assert str(chii.get("final") or "").strip()
    assert all(str(part.get("final") or "").strip() for part in chii["parts"])
