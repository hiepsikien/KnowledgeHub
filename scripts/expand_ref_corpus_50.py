#!/usr/bin/env python3
"""Expand REF corpus to 50 samples, generate expectations, run QA."""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "tests" / "fixtures" / "ref_corpus"
EXCERPT = 4000
UA = "KnowledgeHub-REF-Corpus/1.0"

EN_PG: list[dict] = [
    {"id": "grotius_treatise", "file": "grotius_treatise.txt", "local": True, "family": "gutenberg", "strip_first": True},
    {"id": "grotius_treatise_ch1", "file": "grotius_treatise_ch1.txt", "local": True, "family": "gutenberg", "strip_first": False},
    {"id": "locke_second_treatise", "file": "locke_second_treatise.txt", "gid": "7370", "marker": "CHAPTER I", "strip_first": True},
    {"id": "dickens_two_cities", "file": "dickens_two_cities.txt", "gid": "98", "marker": "It was the best of times", "strip_first": True},
    {"id": "aquinas_summa", "file": "aquinas_summa.txt", "gid": "17611", "marker": "QUESTION 1", "family": "scholastic", "strip_first": True},
    {"id": "aristotle_politics", "file": "aristotle_politics.txt", "gid": "6762", "marker": None, "strip_first": True},
    {"id": "mill_on_liberty", "file": "mill_on_liberty.txt", "gid": "34901", "marker": "CHAPTER I", "strip_first": True},
    {"id": "whitman_grass", "file": "whitman_grass.txt", "gid": "1322", "marker": "Song of Myself", "strip_first": False},
    {"id": "shakespeare_hamlet", "file": "shakespeare_hamlet.txt", "gid": "1524", "marker": "Dramatis Personæ", "strip_first": False},
    {"id": "plato_republic", "file": "plato_republic.txt", "gid": "1497", "marker": "BOOK I", "strip_first": True},
    {"id": "hobbes_leviathan", "file": "hobbes_leviathan.txt", "gid": "3207", "marker": "PART I", "strip_first": True},
    {"id": "machiavelli_prince", "file": "machiavelli_prince.txt", "gid": "1232", "marker": "CHAPTER I", "strip_first": True},
    {"id": "marx_communist", "file": "marx_communist.txt", "gid": "61", "marker": "I. BOURGEOIS", "strip_first": True},
    {"id": "darwin_origin", "file": "darwin_origin.txt", "gid": "1228", "marker": "CHAPTER I", "strip_first": True},
    {"id": "austen_pride", "file": "austen_pride.txt", "gid": "1342", "marker": "Chapter I", "strip_first": True},
    {"id": "melville_moby", "file": "melville_moby.txt", "gid": "2701", "marker": "CHAPTER 1", "strip_first": True},
    {"id": "homer_iliad", "file": "homer_iliad.txt", "gid": "6130", "marker": "BOOK I", "strip_first": True},
    {"id": "hume_treatise", "file": "hume_treatise.txt", "gid": "4705", "marker": "BOOK I", "strip_first": True},
    {"id": "smith_wealth", "file": "smith_wealth.txt", "gid": "3300", "marker": "BOOK I", "strip_first": True},
    {"id": "montesquieu_spirit", "file": "montesquieu_spirit.txt", "gid": "2753", "marker": "BOOK I", "strip_first": True},
    {"id": "paine_common_sense", "file": "paine_common_sense.txt", "gid": "147", "marker": "INTRODUCTION", "strip_first": True},
    {"id": "federalist_papers", "file": "federalist_papers.txt", "gid": "1404", "marker": "FEDERALIST No. 1", "strip_first": True},
    {"id": "swift_gulliver", "file": "swift_gulliver.txt", "gid": "829", "marker": "PART I", "strip_first": True},
    {"id": "bronte_jane_eyre", "file": "bronte_jane_eyre.txt", "gid": "1260", "marker": "CHAPTER I", "strip_first": True},
    {"id": "wells_war_worlds", "file": "wells_war_worlds.txt", "gid": "36", "marker": "CHAPTER ONE", "strip_first": True},
    {"id": "poe_raven", "file": "poe_raven.txt", "gid": "932", "marker": "The Raven", "strip_first": True},
    {"id": "thoreau_walden", "file": "thoreau_walden.txt", "gid": "205", "marker": "Economy", "strip_first": True},
    {"id": "franklin_autobiography", "file": "franklin_autobiography.txt", "gid": "148", "marker": "TWYFORD", "strip_first": True},
    {"id": "cicero_offices", "file": "cicero_offices.txt", "gid": "541", "marker": "BOOK I", "strip_first": True},
    {"id": "kant_critique", "file": "kant_critique.txt", "gid": "4280", "marker": "PREFACE", "strip_first": True},
    {"id": "archive_scan_ocr", "file": "archive_scan_ocr.txt", "local": True, "family": "archive_scan", "strip_first": False},
    {"id": "twain_huckleberry", "file": "twain_huckleberry.txt", "gid": "76", "marker": "CHAPTER I", "strip_first": True},
    {"id": "shelley_frankenstein", "file": "shelley_frankenstein.txt", "gid": "84", "marker": "Letter 1", "strip_first": True},
    {"id": "wilde_dorian", "file": "wilde_dorian.txt", "gid": "174", "marker": "CHAPTER I", "strip_first": True},
    {"id": "verne_journey", "file": "verne_journey.txt", "gid": "18857", "marker": "CHAPTER I", "strip_first": True},
    {"id": "emerson_essays", "file": "emerson_essays.txt", "gid": "16643", "marker": "History", "strip_first": True},
    {"id": "bunyan_pilgrim", "file": "bunyan_pilgrim.txt", "gid": "109", "marker": "THE AUTHOR'S", "strip_first": True},
    {"id": "voltaire_candid", "file": "voltaire_candid.txt", "gid": "19942", "marker": "CHAPTER I", "strip_first": True},
    {"id": "tolstoy_war_peace", "file": "tolstoy_war_peace.txt", "gid": "2600", "marker": "Well, Prince", "strip_first": True},
    {"id": "dostoevsky_crime", "file": "dostoevsky_crime.txt", "gid": "2554", "marker": "PART I", "strip_first": True},
]

VI_WIKI: list[dict] = [
    {"id": "grotius_vi_chviii", "file": "grotius_vi_chviii.txt", "local": True, "source": "hub_translation"},
    {"id": "doan_chinh_phu_ngam", "file": "doan_chinh_phu_ngam.txt", "local": True, "source": "hub_translation"},
    {"id": "qua_deo_ngang", "file": "qua_deo_ngang.txt", "local": True},
    {"id": "ho_banh_troi_nuoc", "file": "ho_banh_troi_nuoc.txt", "title": "Bánh_trôi_nước_(Hồ_Xuân_Hương)"},
    {"id": "le_kien_van_cao_si", "file": "le_kien_van_cao_si.txt", "title": "Văn_Cao_Sĩ_(Lê_Kiến)"},
    {"id": "nam_cao_chi_pheo", "file": "nam_cao_chi_pheo.txt", "title": "Chí_Phèo"},
    {"id": "le_van_dai_phong_tuc", "file": "le_van_dai_phong_tuc.txt", "title": "Phong_tục_Việt_Nam_(Lê_Văn_Đại)"},
    {"id": "truyen_kieu", "file": "truyen_kieu.txt", "title": "Truyện_Kiều"},
    {"id": "vo_nhat", "file": "vo_nhat.txt", "title": "Vợ_nhặt"},
    {"id": "lang_kim_lan", "file": "lang_kim_lan.txt", "title": "Làng_(Kim_Lân)"},
    {"id": "so_do", "file": "so_do.txt", "title": "Số_đỏ"},
    {"id": "tat_den", "file": "tat_den.txt", "title": "Tắt_đèn"},
    {"id": "de_men", "file": "de_men.txt", "title": "Dế_Mèn_phiêu_lưu_ký"},
    {"id": "hon_truong_ba", "file": "hon_truong_ba.txt", "title": "Hồn_Trương_Ba_da_diếc"},
    {"id": "cuoc_doi_ban_ga", "file": "cuoc_doi_ban_ga.txt", "title": "Cuộc_đời_của_bạn_Ga"},
    {"id": "tat_ca_deu", "file": "tat_ca_deu.txt", "title": "Tất_cả_đều_ổn"},
    {"id": "tho_buom_tim", "file": "tho_buom_tim.txt", "title": "Thơ_buom_tim"},
    {"id": "doan_truong_tay_ho", "file": "doan_truong_tay_ho.txt", "title": "Đoàn_trường_Tây_Học"},
    {"id": "phuong_nam", "file": "phuong_nam.txt", "title": "Phương_Nam"},
    {"id": "dat_rung_phuong_nam", "file": "dat_rung_phuong_nam.txt", "title": "Đất_rừng_phương_Nam"},
]

JA: list[dict] = [
    {"id": "aozora_sample", "file": "aozora_sample.txt", "local": True, "family": "aozora"},
    {"id": "aozora_kokoro", "file": "aozora_kokoro.txt", "title": "こころ_(夏目漱石)"},
]


def _fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=90) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _pg(gid: str, marker: str | None) -> str:
    url = f"https://www.gutenberg.org/cache/epub/{gid}/pg{gid}.txt"
    text = _fetch(url)
    if marker:
        idx = text.find(marker)
        if idx >= 0:
            text = text[idx:]
    return text[:EXCERPT]


def _wiki(title: str) -> str:
    q = urllib.parse.quote(title, safe="")
    url = f"https://vi.wikisource.org/w/index.php?title={q}&action=render"
    html = _fetch(url)
    text = re.sub(r"(?is)<script.*?>.*?</script>", "", html)
    text = re.sub(r"(?is)<style.*?>.*?</style>", "", text)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"(?is)<[^>]+>", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()[:EXCERPT]


def _ja_wiki(title: str) -> str:
    q = urllib.parse.quote(title, safe="")
    url = f"https://ja.wikisource.org/w/index.php?title={q}&action=render"
    html = _fetch(url)
    text = re.sub(r"(?is)<script.*?>.*?</script>", "", html)
    text = re.sub(r"(?is)<style.*?>.*?</style>", "", text)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"(?is)<[^>]+>", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()[:EXCERPT]


def build_manifest() -> list[dict]:
    manifest: list[dict] = []
    for row in EN_PG:
        entry = {
            "id": row["id"],
            "file": f"en/{row['file']}",
            "language": "en",
            "family": row.get("family", "gutenberg"),
            "strip_first": row.get("strip_first", True),
        }
        if row.get("gid"):
            entry["gutenberg_id"] = row["gid"]
        manifest.append(entry)
    for row in VI_WIKI:
        manifest.append({
            "id": row["id"],
            "file": f"vi/{row['file']}",
            "language": "vi",
            "family": "plain",
            "source": row.get("source", "vi.wikisource"),
            "strip_first": False,
        })
    for row in JA:
        manifest.append({
            "id": row["id"],
            "file": f"ja/{row['file']}",
            "language": "ja",
            "family": row.get("family", "aozora"),
            "strip_first": False,
        })
    return manifest


def fetch_files() -> None:
    (CORPUS / "en").mkdir(parents=True, exist_ok=True)
    (CORPUS / "vi").mkdir(parents=True, exist_ok=True)
    (CORPUS / "ja").mkdir(parents=True, exist_ok=True)
    for row in EN_PG:
        out = CORPUS / "en" / row["file"]
        if out.exists() and len(out.read_text(encoding="utf-8").strip()) >= 80:
            continue
        if row.get("local"):
            continue
        if row.get("gid"):
            print(f"PG {row['gid']} -> {out.name}")
            out.write_text(_pg(row["gid"], row.get("marker")), encoding="utf-8")
            time.sleep(0.5)
    for row in VI_WIKI:
        out = CORPUS / "vi" / row["file"]
        if out.exists() and len(out.read_text(encoding="utf-8").strip()) >= 80:
            continue
        if row.get("local") and out.exists():
            continue
        if row.get("title"):
            print(f"VI wiki {row['title']} -> {out.name}")
            try:
                out.write_text(_wiki(row["title"]), encoding="utf-8")
            except Exception as exc:
                print(f"  skip {row['id']}: {exc}", file=sys.stderr)
            time.sleep(0.5)
    for row in JA:
        out = CORPUS / "ja" / row["file"]
        if row.get("local") and out.exists():
            continue
        if row.get("title"):
            print(f"JA wiki {row['title']} -> {out.name}")
            try:
                out.write_text(_ja_wiki(row["title"]), encoding="utf-8")
            except Exception as exc:
                print(f"  skip {row['id']}: {exc}", file=sys.stderr)
            time.sleep(0.5)


def auto_expectations(manifest: list[dict], existing: dict) -> dict:
    from knowledgehub.edition.ref_parser import parse_manuscript_to_ref

    out = dict(existing)
    for entry in manifest:
        sid = entry["id"]
        path = CORPUS / entry["file"]
        if not path.exists() or len(path.read_text(encoding="utf-8").strip()) < 80:
            continue
        strip = entry.get("strip_first", entry.get("family") == "gutenberg")
        try:
            edition, _ = parse_manuscript_to_ref(
                path.read_text(encoding="utf-8"),
                language=entry["language"],
                family=entry.get("family"),
                strip_first=strip,
            )
        except Exception as exc:
            print(f"skip expect {sid}: {exc}", file=sys.stderr)
            continue
        blocks = edition["blocks"]
        types = {b["type"] for b in blocks}
        required = ["paragraph"]
        if "heading" in types:
            required.append("heading")
        if "dialogue" in types:
            required.append("dialogue")
        if "stanza" in types:
            required.append("stanza")
        if "list_item" in types:
            required.append("list_item")
        n = len(blocks)
        bounds = {
            "min_blocks": max(1, n - 8),
            "max_blocks": n + 15,
            "required_types": required,
            "content_kind": edition["content_kind"],
        }
        if sid in out:
            out[sid].update(bounds)
        else:
            out[sid] = bounds
    return out


def run_qa(manifest: list[dict], *, use_llm: bool = True) -> dict:
    from knowledgehub.edition.ref_qa import parse_and_qa

    results = []
    rule_pass = llm_ok = llm_err = v_pass = v_warn = v_fail = 0
    for i, entry in enumerate(manifest):
        path = CORPUS / entry["file"]
        if not path.exists():
            continue
        raw = path.read_text(encoding="utf-8")
        if len(raw.strip()) < 80:
            continue
        strip = entry.get("strip_first", entry.get("family") == "gutenberg")
        print(f"[{i+1}/{len(manifest)}] QA {entry['id']}...", flush=True)
        try:
            edition, _, qa = parse_and_qa(
                raw,
                language=entry["language"],
                family=entry.get("family"),
                strip_first=strip,
                use_llm_qa=use_llm,
            )
        except Exception as exc:
            llm_err += 1
            results.append({"id": entry["id"], "error": str(exc), "llm_passed": False, "fidelity_passed": False})
            time.sleep(3)
            continue
        fid = qa.get("fidelity", {}).get("passed", False)
        llm = qa.get("llm") or {}
        rule_pass += int(fid)
        llm_ok += int(qa.get("passed", False) and use_llm)
        if use_llm and llm:
            v = llm.get("verdict", "fail")
            v_pass += int(v == "pass")
            v_warn += int(v == "warn")
            v_fail += int(v == "fail")
        results.append({
            "id": entry["id"],
            "language": entry["language"],
            "blocks": len(edition.get("blocks") or []),
            "fidelity_passed": fid,
            "llm_passed": qa.get("passed") if use_llm else None,
            "model": llm.get("model"),
            "scores": llm.get("scores"),
            "verdict": llm.get("verdict"),
            "issue_count": len(llm.get("issues") or []),
            "summary_vi": llm.get("summary_vi"),
            "error": llm.get("error"),
            "top_issues": (llm.get("issues") or [])[:2],
        })
        if use_llm:
            time.sleep(3)
    return {
        "model": results[0].get("model") if results else None,
        "samples": len(results),
        "rule_passed": rule_pass,
        "llm_ok": llm_ok if use_llm else None,
        "llm_errors": llm_err,
        "verdict_pass": v_pass if use_llm else None,
        "verdict_warn": v_warn if use_llm else None,
        "verdict_fail": v_fail if use_llm else None,
        "results": results,
    }


def main() -> int:
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--fetch-only", action="store_true")
    p.add_argument("--no-llm", action="store_true")
    p.add_argument("--skip-fetch", action="store_true")
    args = p.parse_args()

    manifest = build_manifest()
    # drop entries whose files fail to fetch later
    if not args.skip_fetch:
        fetch_files()

    # keep only samples with files
    ok_manifest = []
    for entry in manifest:
        path = CORPUS / entry["file"]
        if path.exists() and len(path.read_text(encoding="utf-8").strip()) >= 80:
            ok_manifest.append(entry)
    manifest = ok_manifest[:50]
    print(f"manifest: {len(manifest)} samples")

    (CORPUS / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    existing = {}
    exp_path = CORPUS / "expectations.json"
    if exp_path.exists():
        existing = json.loads(exp_path.read_text(encoding="utf-8"))
    expectations = auto_expectations(manifest, existing)
    exp_path.write_text(json.dumps(expectations, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if args.fetch_only:
        return 0

    report = run_qa(manifest, use_llm=not args.no_llm)
    (CORPUS / "qa_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in report if k != "results"}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
