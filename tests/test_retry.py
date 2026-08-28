from __future__ import annotations

import json
import urllib.error
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from knowledgehub.server import create_app
from knowledgehub.settings import llm_call_limits, save_settings
from knowledgehub.translation.jobs import (
    claim_next,
    enqueue_job,
    is_transient_error,
    process_next_job,
    requeue_job,
    retry_delay_for,
)
from knowledgehub.translation.project import init_translation_project, select_translation_mode
from knowledgehub.translation.providers import (
    ProviderError,
    _backoff_delay,
    _retry_after_seconds,
    _RateLimiter,
    gemini_generate,
    reset_rate_limiter,
)

WORK_ID = "grotius--freedom_of_the_seas"

GEMINI_429 = json.dumps(
    {
        "error": {
            "code": 429,
            "message": (
                "You exceeded your current quota. * Quota exceeded for metric: "
                "generate_content_free_tier_requests, limit: 20. Please retry in 20.7s."
            ),
            "status": "RESOURCE_EXHAUSTED",
        }
    }
)
GEMINI_503 = json.dumps(
    {"error": {"code": 503, "message": "This model is currently experiencing high demand."}}
)


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    catalog = tmp_path / "catalog"
    catalog.mkdir()
    sources = tmp_path / "sources/grotius/raw"
    sources.mkdir(parents=True)
    (sources / "freedom_of_the_seas.txt").write_text(
        "CHAPTER I\n\nEnglish paragraph one.\n\nCHAPTER II\n\nEnglish paragraph two.\n",
        encoding="utf-8",
    )
    (catalog / "works.json").write_text(
        json.dumps(
            [
                {
                    "id": WORK_ID,
                    "title": "The Freedom of the Seas",
                    "author_id": "grotius",
                    "language": "en",
                    "content_file": "sources/grotius/raw/freedom_of_the_seas.txt",
                }
            ]
        ),
        encoding="utf-8",
    )
    (catalog / "authors.json").write_text(
        json.dumps([{"id": "grotius", "name": "Grotius"}]), encoding="utf-8"
    )
    monkeypatch.setenv("KNOWLEDGEHUB_CORPUS", str(tmp_path))
    monkeypatch.setenv("KNOWLEDGEHUB_JOB_WORKER", "0")
    monkeypatch.delenv("KNOWLEDGEHUB_OPS_SECRET", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini")
    reset_rate_limiter()
    init_translation_project(WORK_ID)
    sample = tmp_path / f"translations/{WORK_ID}/segments/chi-sample.json"
    payload = json.loads(sample.read_text(encoding="utf-8"))
    payload["drafts"]["tight"] = "Bản dịch tight."
    sample.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    select_translation_mode(WORK_ID, "tight")
    yield TestClient(create_app())
    reset_rate_limiter()


def _http_error(code: int, body: str, *, retry_after: str | None = None):
    headers = {"Retry-After": retry_after} if retry_after else {}
    return urllib.error.HTTPError(
        "https://example.test", code, "err", headers, BytesIO(body.encode("utf-8"))
    )


def test_retry_after_prefers_google_hint():
    assert _retry_after_seconds(None, GEMINI_429) == pytest.approx(20.7)
    assert _retry_after_seconds({"Retry-After": "8"}, "") == pytest.approx(8.0)
    assert _retry_after_seconds(None, "no hint here") is None


def test_backoff_grows_and_is_capped():
    assert _backoff_delay(0, 20.7) == pytest.approx(21.2)
    assert _backoff_delay(0, None) < _backoff_delay(3, None)
    assert _backoff_delay(20, None) <= 90.0


def test_gemini_retries_429_then_succeeds(client: TestClient):
    save_settings({"translation": {"llm_retries": 3}})
    calls: list[int] = []
    ok = {"candidates": [{"content": {"parts": [{"text": "Bản dịch."}]}}]}

    def flaky(req, timeout=300):
        calls.append(1)
        if len(calls) <= 2:
            raise _http_error(429, GEMINI_429)

        class _Resp:
            def read(self):
                return json.dumps(ok).encode("utf-8")

            def __enter__(self):
                return self

            def __exit__(self, *_a):
                return False

        return _Resp()

    with (
        patch("urllib.request.urlopen", side_effect=flaky),
        patch("knowledgehub.translation.providers._guarded_sleep") as slept,
    ):
        assert gemini_generate("hi", model="gemini-3.5-flash") == "Bản dịch."
    assert len(calls) == 3
    assert slept.call_count == 2
    assert slept.call_args_list[0].args[0] == pytest.approx(21.2)


def test_gemini_gives_up_after_configured_retries(client: TestClient):
    save_settings({"translation": {"llm_retries": 1}})

    def always_503(req, timeout=300):
        raise _http_error(503, GEMINI_503)

    with (
        patch("urllib.request.urlopen", side_effect=always_503) as urlopen,
        patch("knowledgehub.translation.providers._guarded_sleep"),
        pytest.raises(ProviderError, match="503"),
    ):
        gemini_generate("hi", model="gemini-3.5-flash")
    assert urlopen.call_count == 2


def test_bad_request_is_not_retried(client: TestClient):
    save_settings({"translation": {"llm_retries": 3}})

    def bad(req, timeout=300):
        raise _http_error(400, '{"error": {"message": "bad model"}}')

    with (
        patch("urllib.request.urlopen", side_effect=bad) as urlopen,
        patch("knowledgehub.translation.providers._guarded_sleep") as slept,
        pytest.raises(ProviderError, match="400"),
    ):
        gemini_generate("hi", model="gemini-3.5-flash")
    assert urlopen.call_count == 1
    assert slept.call_count == 0


class _Slept(Exception):
    """Raised by the fake sleep so a blocked acquire() unwinds instead of spinning."""

    def __init__(self, seconds: float) -> None:
        super().__init__(seconds)
        self.seconds = seconds


def test_rate_limiter_waits_when_window_is_full():
    limiter = _RateLimiter()
    with patch(
        "knowledgehub.translation.providers._guarded_sleep",
        side_effect=lambda seconds: (_ for _ in ()).throw(_Slept(seconds)),
    ):
        for _ in range(3):
            limiter.acquire("gemini", 3)
        with pytest.raises(_Slept) as caught:
            limiter.acquire("gemini", 3)
    assert 0 < caught.value.seconds <= 60.05


def test_rate_limiter_ignores_zero_rpm():
    limiter = _RateLimiter()
    with patch("knowledgehub.translation.providers._guarded_sleep") as slept:
        for _ in range(50):
            limiter.acquire("gemini", 0)
    assert slept.call_count == 0


def test_rate_limiter_reopens_after_window_slides(monkeypatch: pytest.MonkeyPatch):
    limiter = _RateLimiter()
    clock = {"now": 1000.0}
    monkeypatch.setattr(
        "knowledgehub.translation.providers.time.monotonic", lambda: clock["now"]
    )
    monkeypatch.setattr(
        "knowledgehub.translation.providers._guarded_sleep",
        lambda seconds: clock.__setitem__("now", clock["now"] + seconds),
    )
    for _ in range(2):
        limiter.acquire("gemini", 2)
    limiter.acquire("gemini", 2)
    assert clock["now"] == pytest.approx(1060.0)


def test_llm_call_limits_from_settings(client: TestClient):
    save_settings({"translation": {"llm_retries": 5, "gemini_rpm": 7, "deepseek_rpm": 40}})
    retries, rpm = llm_call_limits()
    assert retries == 5
    assert rpm == {"gemini": 7, "deepseek": 40}


def test_llm_call_limits_are_clamped(client: TestClient):
    save_settings({"translation": {"llm_retries": 99, "gemini_rpm": 0, "deepseek_rpm": 999}})
    retries, rpm = llm_call_limits()
    assert retries == 6
    assert rpm == {"gemini": 1, "deepseek": 120}


def test_transient_error_classification():
    assert is_transient_error("HTTP 429: RESOURCE_EXHAUSTED")
    assert is_transient_error("HTTP 503: high demand")
    assert is_transient_error("<urlopen error [Errno 60] Operation timed out>")
    # Finished parts are checkpointed, so retrying only redoes the part that flaked.
    assert is_transient_error("DeepSeek draft part 2 stopped mid-word, output not saved. Ends with: …chư")
    assert is_transient_error("DeepSeek hit max_tokens (finish_reason=length)")
    assert not is_transient_error("HTTP 400: bad request")
    assert not is_transient_error("Segment has empty source_text")
    # Our own guards must not be retried: another attempt would just run long again.
    assert not is_transient_error("no progress for 700s (limit 600s)")
    assert not is_transient_error("job ran 21700s (hard limit 21600s)")


def test_transient_job_error_is_requeued_then_fails(client: TestClient, tmp_path: Path):
    save_settings({"translation": {"max_attempts": 2, "auto_annotate": False, "auto_qa": False}})
    enqueue_job(WORK_ID, "II", "draft")
    with patch(
        "knowledgehub.translation.draft.draft_chapter",
        side_effect=RuntimeError("HTTP 503: high demand"),
    ):
        first = process_next_job()
        assert first["status"] == "queued"

        store = json.loads((tmp_path / ".translation-jobs.json").read_text(encoding="utf-8"))
        job = store["jobs"][0]
        assert job["status"] == "queued"
        assert job["phase"] == "retry"
        assert job["not_before"] > job["heartbeat_at"]
        assert claim_next() is None

        job["not_before"] = "2000-01-01T00:00:00+00:00"
        (tmp_path / ".translation-jobs.json").write_text(
            json.dumps(store, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        second = process_next_job()
        assert second["status"] == "error"
        assert second["attempts"] == 2

    store = json.loads((tmp_path / ".translation-jobs.json").read_text(encoding="utf-8"))
    assert [row["kind"] for row in store["jobs"]] == ["draft"]


def test_permanent_job_error_is_not_requeued(client: TestClient, tmp_path: Path):
    save_settings({"translation": {"max_attempts": 3, "auto_annotate": False, "auto_qa": False}})
    enqueue_job(WORK_ID, "II", "draft")
    with patch(
        "knowledgehub.translation.draft.draft_chapter",
        side_effect=RuntimeError("Segment has empty source_text"),
    ):
        done = process_next_job()
    assert done["status"] == "error"
    store = json.loads((tmp_path / ".translation-jobs.json").read_text(encoding="utf-8"))
    assert store["jobs"][0]["status"] == "error"
    assert "not_before" not in store["jobs"][0]


def test_requeued_job_shows_no_last_error(client: TestClient):
    save_settings({"translation": {"max_attempts": 2, "auto_annotate": False, "auto_qa": False}})
    job = enqueue_job(WORK_ID, "II", "draft")
    assert requeue_job(job["id"], delay_sec=15, error="HTTP 503: high demand")
    project = client.get(f"/api/translations/{WORK_ID}").json()
    row = next(item for item in project["chapters"] if item["chapter"] == "II")
    assert "last_error" not in row
    assert row["jobs"][0]["phase"] == "retry"


def test_truncated_draft_is_retried_and_keeps_finished_parts(client: TestClient, tmp_path: Path):
    save_settings({"translation": {"max_attempts": 2, "auto_annotate": False, "auto_qa": False}})
    enqueue_job(WORK_ID, "II", "draft")
    with patch(
        "knowledgehub.translation.draft.draft_chapter",
        side_effect=ProviderError("DeepSeek draft part 2 stopped mid-word, output not saved."),
    ):
        first = process_next_job()
    assert first["status"] == "queued"
    store = json.loads((tmp_path / ".translation-jobs.json").read_text(encoding="utf-8"))
    assert store["jobs"][0]["phase"] == "retry"


def test_retry_delay_grows_with_attempts():
    assert retry_delay_for(1) == 15.0
    assert retry_delay_for(2) == 30.0
    assert retry_delay_for(99) == 120.0
