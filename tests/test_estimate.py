from knowledgehub.translation.estimate import (
    format_token_estimate,
    missing_draft_preview,
    missing_reason,
)


def test_missing_reason_splits_empty_and_raw_pending():
    assert missing_reason({"completeness": "missing", "has_draft_raw": False}) == "empty"
    assert missing_reason({"completeness": "missing", "has_draft_raw": True}) == "raw_pending"
    assert missing_reason({"completeness": "truncated"}) == "truncated"


def test_missing_preview_counts_incomplete_and_estimates_tokens():
    chapters = [
        {"chapter": "I", "completeness": "ok", "words": 100, "has_draft_raw": True},
        {"chapter": "II", "completeness": "missing", "words": 1000, "has_draft_raw": False},
        {"chapter": "III", "completeness": "truncated", "words": 500, "has_draft_raw": True},
        {"chapter": "IV", "completeness": "polish_pending", "words": 200, "has_draft_raw": True},
    ]
    preview = missing_draft_preview(chapters, auto_annotate=False, auto_qa=False)
    assert preview["count"] == 3
    reasons = {row["reason"]: row["count"] for row in preview["by_reason"]}
    assert reasons["empty"] == 1
    assert reasons["truncated"] == 1
    assert reasons["polish_pending"] == 1
    assert preview["est_tokens"] > 0
    assert preview["est_tokens_label"].startswith("~")
    polish_only = missing_draft_preview(
        [chapters[3]], auto_annotate=False, auto_qa=False
    )["est_tokens"]
    full = missing_draft_preview([chapters[1]], auto_annotate=False, auto_qa=False)["est_tokens"]
    assert full > polish_only


def test_format_token_estimate_buckets():
    assert format_token_estimate(800) == "~800"
    assert format_token_estimate(25000).endswith("nghìn")
    assert "triệu" in format_token_estimate(1_500_000)
