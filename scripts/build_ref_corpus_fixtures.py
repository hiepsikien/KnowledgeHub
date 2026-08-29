#!/usr/bin/env python3
"""Fetch real EN/VI excerpts into tests/fixtures/ref_corpus/."""

from __future__ import annotations

import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "tests" / "fixtures" / "ref_corpus"
EXCERPT_CHARS = 4000
USER_AGENT = "KnowledgeHub-REF-Corpus/1.0 (fixture builder; contact: dev@example.com)"


def _fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _pg_plain(gutenberg_id: str, *, start_marker: str | None = None) -> str:
    url = f"https://www.gutenberg.org/cache/epub/{gutenberg_id}/pg{gutenberg_id}.txt"
    text = _fetch(url)
    if start_marker:
        idx = text.find(start_marker)
        if idx >= 0:
            text = text[idx:]
    return text[:EXCERPT_CHARS]


def _wikisource_html(title: str) -> str:
    url = f"https://vi.wikisource.org/w/index.php?title={title}&action=render"
    html = _fetch(url)
    text = re.sub(r"(?is)<script.*?>.*?</script>", "", html)
    text = re.sub(r"(?is)<style.*?>.*?</style>", "", text)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"(?is)<[^>]+>", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()[:EXCERPT_CHARS]


def main() -> int:
    CORPUS.mkdir(parents=True, exist_ok=True)
    (CORPUS / "en").mkdir(exist_ok=True)
    (CORPUS / "vi").mkdir(exist_ok=True)

    en_jobs: list[tuple[str, str, str | None]] = [
        ("grotius_treatise.txt", "4700", "CHAPTER I"),
        ("locke_second_treatise.txt", "7370", "CHAPTER I"),
        ("dickens_two_cities.txt", "98", "It was the best of times"),
        ("aquinas_summa.txt", "17611", "QUESTION 1"),
        ("aristotle_politics.txt", "6762", None),
        ("mill_on_liberty.txt", "34901", "CHAPTER I"),
        ("whitman_grass.txt", "1322", "Song of Myself"),
        ("shakespeare_hamlet.txt", "1524", "Dramatis Personæ"),
    ]
    for filename, gid, marker in en_jobs:
        out = CORPUS / "en" / filename
        print(f"fetch PG {gid} -> {out.name}")
        out.write_text(_pg_plain(gid, start_marker=marker), encoding="utf-8")

    vi_jobs: list[tuple[str, str]] = [
        ("ho_banh_troi_nuoc.txt", "Bánh_trôi_nước_(Hồ_Xuân_Hương)"),
        ("le_kien_van_cao_si.txt", "Văn_Cao_Sĩ_(Lê_Kiến)"),
        ("nam_cao_chi_pheo.txt", "Chí_Phèo"),
        ("le_van_dai_phong_tuc.txt", "Phong_tục_Việt_Nam_(Lê_Văn_Đại)"),
        ("qua_deo_ngang.txt", "Qua_đèo_Ngang"),
    ]
    for filename, title in vi_jobs:
        out = CORPUS / "vi" / filename
        print(f"fetch wikisource {title} -> {out.name}")
        out.write_text(_wikisource_html(title), encoding="utf-8")

    print("done — update manifest.json / expectations.json if samples changed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
