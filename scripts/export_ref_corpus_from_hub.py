#!/usr/bin/env python3
"""Export REF corpus B (50 samples) from Knowledge Hub catalog — not external PG lists."""

from __future__ import annotations

import io
import json
import re
import sys
import time
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
CORPUS_A = ROOT / "tests" / "fixtures" / "ref_corpus"
CORPUS_B = ROOT / "tests" / "fixtures" / "ref_corpus_b"
CATALOG = ROOT / "corpus" / "catalog" / "works.json"
TRANSLATIONS = ROOT / "corpus" / "translations"
EXCERPT = 4000
UA = "KnowledgeHub-REF-Corpus/1.0"
GUTENBERG_TXT = "https://www.gutenberg.org/cache/epub/{gid}/pg{gid}.txt"

# Corpus A ref ids -> hub work ids (non-obvious pairs).
REF_A_TO_HUB: dict[str, str] = {
    "grotius_treatise": "grotius--freedom_of_the_seas",
    "grotius_treatise_ch1": "grotius--freedom_of_the_seas",
    "grotius_vi_chviii": "grotius--freedom_of_the_seas_vi",
    "doan_chinh_phu_ngam": "doan_thi_diem--chinh_phu_ngam",
    "qua_deo_ngang": "ho_xuan_huong--qua_deo_ngang",
    "ho_banh_troi_nuoc": "ho_xuan_huong--banh_troi_nuoc",
    "le_kien_van_cao_si": "le_quy_don--kien_van_cao_si",
    "nam_cao_chi_pheo": "nam_cao--chi_pheo",
    "le_van_dai_phong_tuc": "le_quy_don--van_dai_lat_phong_tuc",
    "truyen_kieu": "nguyen_du--truyen_kieu",
    "tat_den": "ngo_tat_to--tat_den",
    "archive_scan_ocr": "",
    "aozora_sample": "",
}


def _fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=90) as resp:
        return resp.read()


def _fetch_text(url: str, *, encoding: str = "utf-8") -> str:
    return _fetch(url).decode(encoding, errors="replace")


def _pg(gid: str, marker: str | None = None) -> str:
    text = _fetch_text(GUTENBERG_TXT.format(gid=gid))
    if marker:
        idx = text.lower().find(marker.lower())
        if idx >= 0:
            text = text[idx:]
    return text[:EXCERPT]


def _wiki_title_from_url(url: str) -> str:
    if "action=render" in url:
        parsed = urllib.parse.urlparse(url)
        qs = urllib.parse.parse_qs(parsed.query)
        title = (qs.get("title") or [""])[0]
        if title:
            return title
    if "/wiki/" in url:
        return urllib.parse.unquote(url.split("/wiki/", 1)[1])
    return urllib.parse.unquote(url.rstrip("/").split("/")[-1])


def _wiki_render(url: str) -> str:
    title = _wiki_title_from_url(url)
    q = urllib.parse.quote(title, safe="")
    render_url = f"https://vi.wikisource.org/w/index.php?title={q}&action=render"
    html = _fetch_text(render_url)
    text = re.sub(r"(?is)<script.*?>.*?</script>", "", html)
    text = re.sub(r"(?is)<style.*?>.*?</style>", "", text)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"(?is)<[^>]+>", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()[:EXCERPT]


def _aozora(url: str) -> str:
    html = _fetch_text(url)
    zip_href = re.search(r'href="(\./files/[^"]+\.zip)"', html)
    if not zip_href:
        xhtml = re.search(r'href="(\./files/[^"]+\.html)"', html)
        if not xhtml:
            raise ValueError(f"No Aozora download link in {url}")
        file_url = urllib.parse.urljoin(url, xhtml.group(1))
        raw = _fetch(file_url)
        for enc in ("shift_jis", "cp932", "euc-jp", "utf-8"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            text = raw.decode("utf-8", errors="replace")
    else:
        file_url = urllib.parse.urljoin(url, zip_href.group(1))
        with zipfile.ZipFile(io.BytesIO(_fetch(file_url))) as zf:
            name = zf.namelist()[0]
            raw = zf.read(name)
        for enc in ("shift_jis", "cp932", "euc-jp", "utf-8"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            text = raw.decode("utf-8", errors="replace")
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text[:EXCERPT]


def _ref_id(hub_id: str) -> str:
    """hub id locke--second_treatise -> fixture id locke_second_treatise."""
    return hub_id.replace("--", "_")


def _excluded_from_corpus_a(manifest_a: list[dict]) -> tuple[set[str], set[str]]:
    """Return (hub_work_ids, gutenberg_ids) used by corpus A."""
    hub_ids: set[str] = set()
    gids: set[str] = set()
    works = json.loads(CATALOG.read_text(encoding="utf-8"))
    by_gid = {str(w.get("gutenberg_id")): w["id"] for w in works if w.get("gutenberg_id")}

    for entry in manifest_a:
        ref_id = entry["id"]
        if ref_id in REF_A_TO_HUB:
            hid = REF_A_TO_HUB[ref_id]
            if hid:
                hub_ids.add(hid)
        gid = entry.get("gutenberg_id")
        if gid:
            gids.add(str(gid))
            if str(gid) in by_gid:
                hub_ids.add(by_gid[str(gid)])
        # locke_second_treatise -> locke--second_treatise (when no explicit map)
        if ref_id not in REF_A_TO_HUB and "--" not in ref_id:
            guess = ref_id.replace("_", "--", 1)
            if any(w["id"] == guess for w in works):
                hub_ids.add(guess)
    return hub_ids, gids


def _body_marker(work: dict) -> str | None:
    title = str(work.get("title") or "")
    if "CHAPTER" in title.upper():
        return None
    words = re.findall(r"[A-Za-zÀ-ỹ]{4,}", title)
    return words[0] if words else None


def _load_hub_translation(work: dict) -> str | None:
    derived = work.get("derived_from")
    if not derived:
        return None
    seg_dir = TRANSLATIONS / derived / "segments"
    if not seg_dir.is_dir():
        return None
    parts: list[str] = []
    for path in sorted(seg_dir.glob("*.json")):
        row = json.loads(path.read_text(encoding="utf-8"))
        final = row.get("final") or row.get("drafts", {}).get("tight") or ""
        if final:
            parts.append(final.strip())
        if len("\n\n".join(parts)) >= EXCERPT:
            break
    text = "\n\n".join(parts)[:EXCERPT]
    return text if len(text) >= 80 else None


def load_work_excerpt(work: dict, *, root: Path = ROOT / "corpus") -> str:
    if work.get("origin") == "hub_translation":
        text = _load_hub_translation(work)
        if text:
            return text

    rel = work.get("content_file")
    if rel:
        path = root / rel
        if path.is_file():
            return path.read_text(encoding="utf-8", errors="replace")[:EXCERPT]

    gid = work.get("gutenberg_id")
    if gid:
        marker = _body_marker(work)
        return _pg(str(gid), marker)

    url = work.get("source_url") or ""
    if "wikisource.org" in url:
        return _wiki_render(url)
    if "aozora.gr.jp" in url:
        return _aozora(url)

    raise ValueError(f"No text source for {work.get('id')}")


def _detect_family(work: dict) -> str:
    read = work.get("read") or {}
    edition = read.get("edition") or {}
    if edition.get("family"):
        return str(edition["family"])
    if work.get("origin") == "hub_translation":
        return "plain"
    lic = str(work.get("license_source") or work.get("license") or "")
    if "gutenberg" in lic:
        return "scholastic" if work.get("author_id") == "aquinas" else "gutenberg"
    if "wikisource" in lic:
        return "plain"
    if work.get("language") == "ja":
        return "aozora"
    return "gutenberg" if work.get("gutenberg_id") else "plain"


def select_hub_works(*, count: int = 50) -> list[dict]:
    manifest_a = json.loads((CORPUS_A / "manifest.json").read_text(encoding="utf-8"))
    hub_excl, gid_excl = _excluded_from_corpus_a(manifest_a)
    works = json.loads(CATALOG.read_text(encoding="utf-8"))

    def ok(w: dict) -> bool:
        if w["id"] in hub_excl:
            return False
        gid = w.get("gutenberg_id")
        if gid and str(gid) in gid_excl:
            return False
        return True

    def loadable(w: dict) -> bool:
        if not ok(w):
            return False
        if w.get("origin") == "hub_translation":
            return _load_hub_translation(w) is not None
        if w.get("gutenberg_id"):
            return True
        url = w.get("source_url") or ""
        if "wikisource.org" in url or "aozora.gr.jp" in url:
            return True
        rel = w.get("content_file")
        if rel and (ROOT / "corpus" / rel).is_file():
            return True
        return False

    en = sorted([w for w in works if w.get("language") == "en" and loadable(w)], key=lambda w: w["id"])
    vi = sorted([w for w in works if w.get("language") == "vi" and loadable(w)], key=lambda w: w["id"])
    ja = sorted([w for w in works if w.get("language") == "ja" and loadable(w)], key=lambda w: w["id"])

    picked: list[dict] = []
    picked.extend(en[:37])
    picked.extend(vi[:11])
    picked.extend(ja[:2])
    if len(picked) < count:
        seen = {w["id"] for w in picked}
        extra = [w for w in en[37:] if w["id"] not in seen]
        picked.extend(extra[: count - len(picked)])
    return picked[:count]


def _clean_corpus_b() -> None:
    """Remove stale fixture files from prior non-hub exports."""
    if not CORPUS_B.is_dir():
        return
    for sub in ("en", "vi", "ja"):
        d = CORPUS_B / sub
        if d.is_dir():
            for path in d.glob("*.txt"):
                path.unlink()


def export_corpus_b(*, count: int = 50) -> list[dict]:
    _clean_corpus_b()
    manifest_a = json.loads((CORPUS_A / "manifest.json").read_text(encoding="utf-8"))
    hub_excl, gid_excl = _excluded_from_corpus_a(manifest_a)
    works = json.loads(CATALOG.read_text(encoding="utf-8"))

    def ok(w: dict) -> bool:
        if w["id"] in hub_excl:
            return False
        gid = w.get("gutenberg_id")
        if gid and str(gid) in gid_excl:
            return False
        return True

    def loadable(w: dict) -> bool:
        if not ok(w):
            return False
        if w.get("origin") == "hub_translation":
            return _load_hub_translation(w) is not None
        if w.get("gutenberg_id"):
            return True
        url = w.get("source_url") or ""
        if "wikisource.org" in url or "aozora.gr.jp" in url:
            return True
        rel = w.get("content_file")
        if rel and (ROOT / "corpus" / rel).is_file():
            return True
        return False

    candidates = sorted(
        [w for w in works if w.get("language") in {"en", "vi", "ja"} and loadable(w)],
        key=lambda w: (0 if w.get("language") == "en" else 1 if w.get("language") == "vi" else 2, w["id"]),
    )
    manifest: list[dict] = []
    used: set[str] = set()
    en_n = vi_n = ja_n = 0

    for work in candidates:
        if len(manifest) >= count:
            break
        lang = work.get("language") or "en"
        if en_n >= 37 and vi_n >= 11 and ja_n >= 2:
            break
        if lang == "en" and en_n >= 37:
            continue
        if lang == "vi" and vi_n >= 11:
            continue
        if lang == "ja" and ja_n >= 2:
            continue
        if work["id"] in used:
            continue
        used.add(work["id"])

        ref_id = _ref_id(work["id"])
        sub = {"en": "en", "vi": "vi", "ja": "ja"}.get(lang, "en")
        fname = f"{ref_id}.txt"
        out_dir = CORPUS_B / sub
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / fname

        print(f"  {work['id']} -> {sub}/{fname}", flush=True)
        try:
            text = load_work_excerpt(work)
        except Exception as exc:
            print(f"    SKIP: {exc}", file=sys.stderr)
            continue
        if len(text.strip()) < 80:
            print("    SKIP: too short", file=sys.stderr)
            continue
        out.write_text(text, encoding="utf-8")

        family = _detect_family(work)
        entry = {
            "id": ref_id,
            "hub_work_id": work["id"],
            "file": f"{sub}/{fname}",
            "language": lang,
            "family": family,
            "strip_first": family in {"gutenberg", "scholastic"},
            "source": "hub_catalog",
        }
        if work.get("gutenberg_id"):
            entry["gutenberg_id"] = str(work["gutenberg_id"])
        manifest.append(entry)
        if lang == "en":
            en_n += 1
        elif lang == "vi":
            vi_n += 1
        elif lang == "ja":
            ja_n += 1
        time.sleep(0.3)

    (CORPUS_B / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Exported {len(manifest)} samples -> {CORPUS_B} (en={en_n}, vi={vi_n}, ja={ja_n})")
    return manifest


def main() -> int:
    import argparse

    p = argparse.ArgumentParser(description="Export REF corpus B from Knowledge Hub catalog")
    p.add_argument("--count", type=int, default=50)
    args = p.parse_args()
    manifest = export_corpus_b(count=args.count)
    return 0 if len(manifest) >= args.count else 1


if __name__ == "__main__":
    sys.exit(main())
