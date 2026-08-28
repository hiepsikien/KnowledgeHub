#!/usr/bin/env python3
"""One-shot ingest of vietsu Group A PD works. Prefers Wikisource; S3 PDF fallback."""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "corpus" / "sources"
UA = "KnowledgeHub/1.0 (PD corpus ingest; https://github.com/hiepsikien/KnowledgeHub)"
WS_API = "https://vi.wikisource.org/w/api.php"
WP_API = "https://vietsu.org/wp-json/wp/v2/posts"
SLEEP = 0.45

BOILERPLATE = re.compile(
    r"(?m)^(Public domainPublic domainfalsefalse|Tìm kiếm|Bố cục \d+)\s*$"
)
FOOTER = re.compile(r"Lấy từ “[^”]+”\s*$")


def quote_url(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    path = urllib.parse.quote(urllib.parse.unquote(parts.path), safe="/")
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, path, parts.query, parts.fragment))


def request(url: str, retries: int = 8) -> bytes:
    last: Exception | None = None
    delay = 2.0
    url = quote_url(url)
    for _ in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=90) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code in {429, 500, 502, 503}:
                time.sleep(delay)
                delay = min(delay * 2, 60)
                continue
            raise
        except urllib.error.URLError as exc:
            last = exc
            time.sleep(delay)
            delay = min(delay * 2, 60)
    raise RuntimeError(f"failed {url}: {last}")


def ws_get(params: dict) -> dict:
    q = urllib.parse.urlencode({**params, "format": "json"})
    return json.loads(request(WS_API + "?" + q).decode())


def allpages(prefix: str) -> list[str]:
    titles: list[str] = []
    cont: dict = {}
    while True:
        params = {
            "action": "query",
            "list": "allpages",
            "apprefix": prefix,
            "aplimit": "500",
            "apnamespace": "0",
        }
        params.update(cont)
        data = ws_get(params)
        titles.extend(p["title"] for p in data.get("query", {}).get("allpages", []))
        if "continue" in data:
            cont = data["continue"]
            time.sleep(SLEEP)
        else:
            break
    return titles


def leaves(titles: list[str], *, prefix: str, extra_exclude: tuple[str, ...] = ()) -> list[str]:
    title_set = set(titles)
    out = []
    for title in titles:
        if extra_exclude and any(part in title for part in extra_exclude):
            continue
        if title != prefix and not title.startswith(prefix + "/"):
            continue
        if any(other.startswith(title + "/") for other in title_set):
            continue
        out.append(title)
    return natural_sort(out)


_ROMAN = {
    "i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7,
    "viii": 8, "ix": 9, "x": 10, "xi": 11, "xii": 12, "xiii": 13,
    "xiv": 14, "xv": 15, "xvi": 16, "xvii": 17, "xviii": 18, "xix": 19,
    "xx": 20, "xxi": 21, "xxii": 22,
}
_VN_ORD = {
    "nhất": 1, "nhat": 1,
    "hai": 2,
    "ba": 3,
    "tư": 4, "tu": 4,
    "năm": 5, "nam": 5,
    "sáu": 6, "sau": 6,
    "bảy": 7, "bay": 7,
    "tám": 8, "tam": 8,
    "chín": 9, "chin": 9,
    "mười": 10, "muoi": 10,
}


def natural_key(title: str):
    keys = []
    for seg in title.split("/"):
        seg_l = seg.strip().lower()
        if seg_l in {"tựa", "loi mo dau", "lời mở đầu", "lời tựa", "lời phát đoan", "mấy câu giới thiệu"}:
            keys.append((0, 0, ""))
            continue
        m = re.match(
            r"^(chương|cuốn thứ|tập|quyển|phần)\s+([ivxlc]+|\d+|nhất|nhat|hai|ba|tư|tu|năm|nam|sáu|sau|bảy|bay|tám|tam|chín|chin|mười|muoi)$",
            seg_l,
        )
        if m:
            num = m.group(2)
            if num.isdigit():
                n = int(num)
            else:
                n = _ROMAN.get(num) or _VN_ORD.get(num) or 99
            keys.append((1, n, ""))
            continue
        atoms = []
        for chunk in re.split(r"(\d+)", seg_l):
            if not chunk:
                continue
            if chunk.isdigit():
                atoms.append((0, int(chunk), ""))
            elif chunk in _ROMAN:
                atoms.append((0, _ROMAN[chunk], ""))
            else:
                atoms.append((1, 0, chunk))
        keys.append((2, tuple(atoms)))
    return keys


def natural_sort(titles: list[str]) -> list[str]:
    return sorted(titles, key=natural_key)


from html.parser import HTMLParser


class _WikiText(HTMLParser):
    skip_classes = {"ws-noexport", "noprint", "dynlayout-exempt", "mw-editsection"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if self.skip:
            self.skip += 1
            return
        cls = " ".join(dict(attrs).get("class", "").split())
        if any(name in cls.split() for name in self.skip_classes):
            self.skip = 1
            return
        if tag in {"br", "p", "div", "tr", "li", "h1", "h2", "h3", "h4"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if self.skip:
            self.skip -= 1
            return
        if tag in {"p", "div", "h1", "h2", "h3", "h4", "li"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def html_to_text(raw_html: str) -> str:
    parser = _WikiText()
    parser.feed(raw_html)
    text = "".join(parser.parts)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def parse_page(title: str) -> str:
    data = ws_get(
        {
            "action": "parse",
            "page": title,
            "prop": "text",
            "disablelimitreport": "1",
            "redirects": "1",
        }
    )
    raw = ((data.get("parse") or {}).get("text") or {}).get("*") or ""
    return html_to_text(raw)


def clean(text: str) -> str:
    text = FOOTER.sub("", text)
    text = BOILERPLATE.sub("", text)
    text = re.sub(r"(?m)^\.mw-parser-output.*\n?", "", text)
    drop = (
        "tusachtiengviet.com",
        "TVE-4U",
        "SỐ HÓA 1000",
        "vietnamvanhien.net",
        "Biên tập ebook",
        "Đánh máy :",
        "Đánh máy:",
    )
    lines = [ln for ln in text.splitlines() if not any(tok in ln for tok in drop)]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def heading_from_title(root: str, title: str) -> str:
    if title == root:
        return root
    rest = title[len(root) :].lstrip("/")
    return rest.replace("/", " · ")


def fetch_wikisource(root: str, extra_exclude: tuple[str, ...] = ()) -> str:
    titles = allpages(root)
    leaf = leaves(titles, prefix=root, extra_exclude=extra_exclude)
    if not leaf:
        raise RuntimeError(f"no Wikisource leaves for {root!r} (saw {len(titles)} pages)")
    chunks: list[str] = []
    for i, title in enumerate(leaf, 1):
        print(f"  parse {i}/{len(leaf)} {title}", flush=True)
        body = clean(parse_page(title))
        time.sleep(SLEEP)
        if len(body) < 80:
            continue
        head = heading_from_title(root, title)
        chunks.append(f"{head}\n\n{body}" if title != root else body)
    text = clean("\n\n\n".join(chunks))
    if len(text) < 1000:
        raise RuntimeError(f"{root}: assembled text too short ({len(text)} chars, {len(leaf)} leaves)")
    return text


def decode_s3(html: str) -> str | None:
    import base64

    matches = re.findall(r"tnc_pvfw=([A-Za-z0-9+/=]+)", html)
    for token in matches:
        pad = "=" * ((4 - len(token) % 4) % 4)
        try:
            decoded = base64.b64decode(token + pad).decode("utf-8", errors="replace")
        except Exception:
            continue
        qs = urllib.parse.parse_qs(decoded)
        files = qs.get("file") or []
        if files:
            return files[0]
    urls = re.findall(r"https://vietsu\.s3[^\s\"'<>]+\.pdf", html)
    return urls[0] if urls else None


def fetch_vietsu_pdf_text(slug: str) -> tuple[str, str]:
    from pypdf import PdfReader
    import io

    payload = json.loads(
        request(f"{WP_API}?slug={urllib.parse.quote(slug)}").decode()
    )
    if not payload:
        raise RuntimeError(f"no WP post for slug={slug}")
    html = payload[0].get("content", {}).get("rendered") or ""
    pdf_url = decode_s3(html)
    if not pdf_url:
        raise RuntimeError(f"no PDF URL for {slug}")
    print(f"  S3 {pdf_url}", flush=True)
    raw = request(pdf_url)
    reader = PdfReader(io.BytesIO(raw))
    pages = []
    for page in reader.pages:
        pages.append(page.extract_text() or "")
    text = clean("\n\n".join(pages))
    if len(re.findall(r"[A-Za-zÀ-ỹ]", text)) < 400:
        raise RuntimeError(f"{slug}: PDF looks like a scan ({len(text)} chars)")
    return text, pdf_url


def fetch_commons_pdf_text(filename: str) -> str:
    from pypdf import PdfReader
    import io

    url = "https://commons.wikimedia.org/wiki/Special:FilePath/" + urllib.parse.quote(filename)
    print(f"  Commons {filename}", flush=True)
    raw = request(url)
    reader = PdfReader(io.BytesIO(raw))
    pages = [(page.extract_text() or "") for page in reader.pages]
    text = clean("\n\n".join(pages))
    letters = len(re.findall(r"[A-Za-zÀ-ỹ]", text))
    if letters < 400:
        raise RuntimeError(
            f"{filename}: scan PDF, no extractable text ({letters} letters, "
            f"{len(reader.pages)} pages). Refusing vietsu Alpha Books 2016 edition."
        )
    return text


def write_work(brain: str, filename: str, text: str, meta: dict) -> None:
    raw_dir = SOURCES / brain / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = raw_dir / filename
    path.write_text(text.rstrip() + "\n", encoding="utf-8")
    works_path = SOURCES / brain / "works.json"
    rows = []
    if works_path.is_file():
        rows = json.loads(works_path.read_text(encoding="utf-8"))
    rows = [r for r in rows if r.get("file") != filename]
    rows.append(meta)
    works_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"  wrote {path.relative_to(ROOT)} ({len(text):,} chars)", flush=True)


def row(**kwargs) -> dict:
    meta = {
        "gutenberg_id": None,
        "license": "public_domain_vn_wikisource",
        "lang": "vi",
        "chunking": "prose",
    }
    meta.update(kwargs)
    return meta


JOBS = [
    {
        "brain": "tran_trong_kim",
        "file": "viet_nam_su_luoc.txt",
        "kind": "wikisource",
        "root": "Việt Nam sử lược",
        "exclude": ("/1923/", "/1928/", "/1971/"),
        "meta": row(
            file="viet_nam_su_luoc.txt",
            work="Việt Nam sử lược",
            year=1921,
            source_url="https://vi.wikisource.org/wiki/Việt_Nam_sử_lược",
            translator=None,
            concepts=["su luoc", "viet nam", "lich su", "trieu dai"],
        ),
    },
    {
        "brain": "tran_trong_kim",
        "file": "phat_giao.txt",
        "kind": "wikisource",
        "root": "Phật giáo",
        "exclude": ("triết học", "Triết học"),
        "meta": row(
            file="phat_giao.txt",
            work="Phật giáo",
            year=1940,
            source_url="https://vi.wikisource.org/wiki/Phật_giáo",
            translator=None,
            concepts=["phat giao", "nhan sinh", "thap nhi nhan duyen", "dai thua"],
        ),
    },
    {
        "brain": "phan_ke_binh",
        "file": "nam_hai_di_nhan_liet_truyen.txt",
        "kind": "wikisource",
        "root": "Nam Hải dị nhân liệt truyện",
        "meta": row(
            file="nam_hai_di_nhan_liet_truyen.txt",
            work="Nam Hải dị nhân liệt truyện",
            year=1909,
            source_url="https://vi.wikisource.org/wiki/Nam_Hải_dị_nhân_liệt_truyện",
            translator=None,
            concepts=["di nhan", "truyen ky", "danh nhan", "lich su"],
        ),
    },
    {
        "brain": "ngo_tat_to",
        "file": "hoang_le_nhat_thong_chi.txt",
        "kind": "wikisource",
        "root": "Hoàng Lê nhất thống chí",
        "meta": row(
            file="hoang_le_nhat_thong_chi.txt",
            work="Hoàng Lê nhất thống chí (Ngô Tất Tố dịch)",
            year=1945,
            source_url="https://vi.wikisource.org/wiki/Hoàng_Lê_nhất_thống_chí",
            translator="Ngô Tất Tố (1894–1954) — Mai Lĩnh 1945, VN PD",
            concepts=["tay son", "le chieu thong", "nguyen hue", "tieu thuyet lich su"],
        ),
    },
    {
        "brain": "le_ngo_cat",
        "file": "dai_nam_quoc_su_dien_ca.txt",
        "kind": "wikisource",
        "root": "Đại Nam Quốc sử Diễn ca",
        "meta": row(
            file="dai_nam_quoc_su_dien_ca.txt",
            work="Đại Nam quốc sử diễn ca",
            year=1870,
            source_url="https://vi.wikisource.org/wiki/Đại_Nam_Quốc_sử_Diễn_ca",
            translator="Lê Ngô Cát / Phạm Đình Toái — quốc ngữ PD",
            chunking="verse",
            concepts=["dien ca", "luc bat", "lich su", "dai nam"],
        ),
    },
    {
        "brain": "truong_vinh_ky",
        "file": "chuyen_di_bac_ky.txt",
        "kind": "wikisource",
        "root": "Chuyến đi Bắc Kỳ năm Ất Hợi 1876",
        "meta": row(
            file="chuyen_di_bac_ky.txt",
            work="Chuyến đi Bắc Kỳ năm Ất Hợi 1876",
            year=1876,
            source_url="https://vi.wikisource.org/wiki/Chuyến_đi_Bắc_Kỳ_năm_Ất_Hợi_1876",
            translator=None,
            concepts=["memoir", "du ky", "bac ky", "nam ky"],
        ),
    },
    {
        "brain": "ngo_si_lien",
        "file": "dai_viet_su_ky_toan_thu.txt",
        "kind": "wikisource",
        "root": "Đại Việt sử ký toàn thư",
        "meta": row(
            file="dai_viet_su_ky_toan_thu.txt",
            work="Đại Việt sử ký toàn thư (Mạc Bảo Thần / Nhượng Tống dịch, Tân Việt 1945 — Ngoại kỷ đến nhà Ngô)",
            year=1945,
            source_url="https://vi.wikisource.org/wiki/Đại_Việt_sử_ký_toàn_thư",
            translator="Mạc Bảo Thần (Nhượng Tống, Hoàng Phạm Trân, 1906–1949) — VN PD",
            concepts=["toan thu", "ngoai ky", "bien nien", "dai viet"],
        ),
    },
    {
        "brain": "nguyen_trai",
        "file": "lam_son_thuc_luc.txt",
        "kind": "wikisource",
        "root": "Lam Sơn thực lục",
        "meta": row(
            file="lam_son_thuc_luc.txt",
            work="Lam Sơn thực lục (Mạc Bảo Thần dịch)",
            year=1945,
            source_url="https://vi.wikisource.org/wiki/Lam_Sơn_thực_lục",
            translator="Mạc Bảo Thần (Nhượng Tống, 1906–1949) — Tân Việt, VN PD",
            concepts=["lam son", "le loi", "khoi nghia", "thuc luc"],
        ),
    },
    {
        "brain": "dao_trinh_nhat",
        "file": "phan_dinh_phung.txt",
        "kind": "s3",
        "slug": "phan-dinh-phung",
        "ws_try": "Phan Đình Phùng",
        "meta": row(
            file="phan_dinh_phung.txt",
            work="Phan Đình Phùng",
            year=1936,
            source_url="https://vietsu.org/phan-dinh-phung/",
            translator=None,
            concepts=["can vuong", "phan dinh phung", "khang phap", "memoir"],
            license="public_domain_vn_wikisource",
        ),
    },
    {
        "brain": "le_van_hoe",
        "file": "tuc_ngu_luoc_giai.txt",
        "kind": "s3_multi",
        "slugs": [
            "tuc-ngu-luoc-giai-tap-1-3",
            "tuc-ngu-luoc-giai-tap-2-3",
            "tuc-ngu-luoc-giai-tap-3-3",
        ],
        "ws_try": "Tục ngữ lược giải",
        "meta": row(
            file="tuc_ngu_luoc_giai.txt",
            work="Tục ngữ lược giải",
            year=1952,
            source_url="https://vietsu.org/tuc-ngu-luoc-giai-tap-1-3/",
            translator=None,
            concepts=["tuc ngu", "ca dao", "van hoa", "giai nghia"],
        ),
    },
    {
        "brain": "cao_xuan_duc",
        "file": "quoc_trieu_chinh_bien_toat_yeu.txt",
        "kind": "s3",
        "slug": "quoc-trieu-chanh-bien-toat-yeu",
        "ws_try": "Quốc triều chính biên toát yếu",
        "meta": row(
            file="quoc_trieu_chinh_bien_toat_yeu.txt",
            work="Quốc triều chính biên toát yếu",
            year=1908,
            source_url="https://vietsu.org/quoc-trieu-chanh-bien-toat-yeu/",
            translator=None,
            concepts=["nha nguyen", "chinh bien", "toat yeu", "bien nien"],
        ),
    },
    {
        "brain": "truc_khe",
        "file": "tran_thu_do.txt",
        "kind": "s3",
        "slug": "tran-thu-do",
        "ws_try": "Trần Thủ Độ",
        "meta": row(
            file="tran_thu_do.txt",
            work="Trần Thủ Độ",
            year=1930,
            source_url="https://vietsu.org/tran-thu-do/",
            translator=None,
            concepts=["tran thu do", "nha tran", "tieu su"],
        ),
    },
    {
        "brain": "truc_khe",
        "file": "lich_su_nam_tien.txt",
        "kind": "s3",
        "slug": "lich-su-nam-tien-cua-dan-toc-viet-nam",
        "ws_try": "Lịch sử Nam tiến của dân tộc Việt Nam",
        "meta": row(
            file="lich_su_nam_tien.txt",
            work="Lịch sử Nam tiến của dân tộc Việt Nam",
            year=1930,
            source_url="https://vietsu.org/lich-su-nam-tien-cua-dan-toc-viet-nam/",
            translator=None,
            concepts=["nam tien", "cham pa", "mo coi", "lich su"],
        ),
    },
    {
        "brain": "tran_trong_kim",
        "file": "nho_giao.txt",
        "kind": "wikisource",
        "root": "Nho giáo",
        "meta": row(
            file="nho_giao.txt",
            work="Nho giáo",
            year=1930,
            source_url="https://vi.wikisource.org/wiki/Nho_giáo",
            translator=None,
            concepts=["nho giao", "khong tu", "luan ly", "triet hoc"],
            pdNotes="Four quyển as one work from Wikisource unversioned tree.",
        ),
    },
    {
        "brain": "ngo_tat_to",
        "file": "leu_chong.txt",
        "kind": "wikisource",
        "root": "Lều chõng",
        "meta": row(
            file="leu_chong.txt",
            work="Lều chõng",
            year=1939,
            source_url="https://vi.wikisource.org/wiki/Lều_chõng",
            translator=None,
            concepts=["khoa cu", "si tu", "lang que", "tieu thuyet"],
        ),
    },
    {
        "brain": "ngo_tat_to",
        "file": "le_van_duyet.txt",
        "kind": "commons_pdf",
        "commons_file": "Gia Dinh tong tran ta quan Le Van Duyet.pdf",
        "ws_try": "Gia Định tổng trấn tả quân Lê Văn Duyệt",
        "meta": row(
            file="le_van_duyet.txt",
            work="Gia Định tổng trấn tả quân Lê Văn Duyệt",
            year=1937,
            source_url="https://commons.wikimedia.org/wiki/File:Gia_Dinh_tong_tran_ta_quan_Le_Van_Duyet.pdf",
            translator=None,
            concepts=["le van duyet", "gia dinh", "nha nguyen", "tieu su"],
            pdNotes="Mai Lĩnh 1937 scan on Wikimedia Commons (Gallica). Not the Alpha Books Góc nhìn sử Việt 2016 edition on vietsu.",
        ),
    },
]


def try_ws_first(job: dict) -> str | None:
    root = job.get("ws_try")
    if not root:
        return None
    try:
        titles = allpages(root)
    except Exception as exc:
        print(f"  WS probe failed for {root}: {exc}")
        return None
    time.sleep(SLEEP)
    if not titles:
        return None
    print(f"  Wikisource hit {root} ({len(titles)} pages) — using WS")
    job["meta"]["source_url"] = f"https://vi.wikisource.org/wiki/{root.replace(' ', '_')}"
    job["meta"]["license"] = "public_domain_vn_wikisource"
    return fetch_wikisource(root, tuple(job.get("exclude") or ()))


def run_job(job: dict) -> str:
    kind = job["kind"]
    if kind == "wikisource":
        return fetch_wikisource(job["root"], tuple(job.get("exclude") or ()))
    ws_text = try_ws_first(job)
    if ws_text:
        return ws_text
    if kind == "s3":
        text, url = fetch_vietsu_pdf_text(job["slug"])
        job["meta"]["source_url"] = url
        job["meta"]["pdNotes"] = f"PDF via vietsu.org/{job['slug']}/ (S3); author PD"
        return text
    if kind == "s3_multi":
        parts = []
        urls = []
        for i, slug in enumerate(job["slugs"], 1):
            print(f"  volume {i}/{len(job['slugs'])} {slug}")
            text, url = fetch_vietsu_pdf_text(slug)
            parts.append(f"Tập {i}\n\n{text}")
            urls.append(url)
            time.sleep(SLEEP)
        job["meta"]["source_url"] = urls[0]
        job["meta"]["pdNotes"] = "PDF 3 tập via vietsu S3; gộp 1 work; author Lê Văn Hòe PD 2019"
        return "\n\n\n".join(parts)
    if kind == "commons_pdf":
        return fetch_commons_pdf_text(job["commons_file"])
    raise ValueError(kind)


def main() -> None:
    only = set()
    import sys

    if len(sys.argv) > 1:
        only = set(sys.argv[1:])
    results = []
    for job in JOBS:
        key = f"{job['brain']}/{job['file']}"
        if only and key not in only and job["file"] not in only:
            continue
        print(f"\n== {key} ==", flush=True)
        try:
            text = run_job(job)
            write_work(job["brain"], job["file"], text, job["meta"])
            results.append((key, "ok", len(text)))
        except Exception as exc:
            print(f"  FAIL: {exc}", flush=True)
            results.append((key, f"FAIL: {exc}", 0))
    print("\n=== summary ===")
    for key, status, n in results:
        print(f"{status:4} {n:8}  {key}" if status == "ok" else f"FAIL      0  {key}  {status}")


if __name__ == "__main__":
    main()
