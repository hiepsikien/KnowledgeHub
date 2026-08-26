# Knowledge Hub — Phase 0 audit (Think CMS + corpus)

> Audit local clone Think (`/Users/andynguyen/projects/Think`), 2026-08-27.  
> Không đọc `.env`. Không đụng raw PD ngoài đếm file.  
> Nguồn: `apps/cms`, `apps/api/think_salon`, `corpus/`, `scripts/ingest_pd.py`.

**Kết luận ngắn:** Think đã có CMS curator + license + ingest `.txt` → chunks. Runtime **không** đọc toàn văn `.txt`. Hub không phải greenfield CMS — thiếu lớp **Work identity / version / publish-to-consumer**. Giả định trong `docs/PROJECT.md` (“mỗi file = một tác phẩm độc lập, metadata author chưa thống nhất”) **đúng một phần**, nhưng mô hình thật là **brain-centric**, không phải catalog sách độc lập.

---

## 1. Sửa giả định so với PROJECT.md

| PROJECT.md (planning) | Think thực tế |
|-----------------------|----------------|
| CMS trong `apps/` | Đúng: `apps/cms` (Vite/React) + API `apps/api` prefix `/admin` |
| Corpus **plain `.txt`** là đơn vị runtime | `.txt` chỉ là **ingest input** (`sources/<brain>/raw/`, gitignored). Runtime = `chunks.jsonl` + forest markdown |
| Không có series / glossary nhân vật | Đúng cho tác phẩm. Có `glossary_vi.md` (từ điển nói VN), không phải character glossary |
| Metadata author chưa thống nhất | **Không có entity Author.** Tác giả ≈ `brain.id`. Work gắn brain, không có `author_id` |
| License đã quản lý trong CMS | Có UI + audit + catalog `licenses.json`, nhưng **string license thực tế lệch catalog** (nhiều id ad-hoc) |
| Think app đọc file `.txt` trực tiếp | **Sai.** Mobile bundle catalog TS; salon đọc **chunks + forest** trên API |

Câu hỏi mở #4 (PROJECT.md §11): corpus lưu filesystem hay DB?  
**Filesystem.** Sau Phase 0: canonical `.txt` chuyển sang **KnowledgeHub/corpus** (`KNOWLEDGEHUB_CORPUS`). Think runtime vẫn là chunks trên Git/GCS. SQLite không chứa corpus.

---

## 2. Map CMS

### 2.1 Stack

| Lớp | Công nghệ | Vai trò |
|-----|-----------|---------|
| `apps/cms` (`@think/cms`) | Vite 6 + React 19, hash-router | Curator UI — secret `THINK_OPS_SECRET` |
| `apps/api` (`think_salon`) | FastAPI / uvicorn :8787 | Salon + `/admin/*` |
| Proxy CMS | Vite `server.proxy` `/admin` → API | Cookie ops |
| Corpus | JSON / Markdown / JSONL trên disk | Source of truth curator |
| Runtime cloud | GCS bucket `think-corpus-*`, sync **không** upload `raw/` | Cloud Run đọc FUSE |
| Catalog app | `scripts/generate_shared_catalog.py` → `packages/shared` + `corpus/registry/catalog.{vi,en,ja}.json` | Mobile không đọc `corpus/` trực tiếp |
| Auth admin | Header `X-Think-Ops-Secret` hoặc cookie | Không có RBAC đa user curator |

Trang CMS: Shelf, Completeness, Onboard, License & PD, Glossary, Ops, Users, Brain (tabs Profile / Forest / Corpus / Chunks).

### 2.2 Models (không có ORM corpus)

**Brain** (`corpus/registry/brains.json`) — 286 entries:

`id`, `name`, `spaceIds[]`, `forestPath`, `ragCollection` (`brain_<id>`), `ttsVoiceId`, `forestStatus` (`draft` \| `approved`), `ready` (bool).

**Profile** (`corpus/profiles/<id>.json`): `brainId`, `birthYear`, `deathYear`, `corpusKind`, `corpusNote`, `portrait`, `copy.{vi,en,ja}` (status, displayName, blurb, biography, quotes, works[].title + `corpusWorks[]`).

**Work ingest** (`corpus/sources/<brain>/works.json`) — array, mỗi phần tử ≈ một file `.txt`:

| Field | Bắt buộc trên data hiện tại | Ghi chú |
|-------|-----------------------------|---------|
| `file` | ✓ 568/568 | Tên file trong `raw/` |
| `work` | ✓ | **Title string** — không có UUID |
| `year` | ✓ | Năm xuất bản / bản PD |
| `license` | ✓ | String, validate prefix `public_domain` \| `cc0` \| `cc_by` |
| `source_url` | ✓ | |
| `concepts` | ✓ | Tag cho RAG / sample ranking |
| `gutenberg_id` | 562/568 | Rỗng với nguồn khác PG |
| `translator` | 560/568 | |
| `lang` | 129/568 | Mặc định EN nếu thiếu (`retrieve.corpus_lang`) |
| `chunking` | 111/568 | `prose` \| `verse` |
| `aozora_card` / `aozora_zip` | 12 | Nhật |
| `authorDeathYear`, `textLayer`, `pdOverride`, `pdNotes`, `pdBasis` | hiếm / CMS ghi khi save | Form CorpusDoc có; data gần như chưa fill |

**Chunk** (`chunks/chunks.jsonl`) — đơn vị retrieve:

`id` (dạng `{brain}_{slug}_{idx}_{sha1-10}`), `brain`, `work` (title), `year`, `license`, `source_url`, `gutenberg_id`, `translator`, `section`, `concepts`, `lang`, `text`, `char_count`.

**Không có:** `content_hash` toàn văn, `version`, `status` publish, `publications`, consumer flags (`think` / `read`).

`chunk_id` hash SHA-1 **đoạn**, không phải hash file gốc.

### 2.3 License

- Catalog: `corpus/licenses.json` (15 id: Gutenberg, Archive, OLL, Wikisource VN, Nôm/quốc ngữ/Hán–Việt, EU, CC0, CC BY, Aozora).
- CMS: `GET /admin/licenses`, `GET /admin/license-audit` (filter region vn/us, blocked, missing raw, stale PD meta).
- PD VN: `think_salon/pd_vietnam.py` — đời+50, TRIPS, chặn `modern_translation`, override curator.
- Save works: regex `_LICENSE_OK = public_domain|cc0|cc_by` rồi `validate_work_for_save`.
- Gia hạn: `corpus/pd_vn_extensions.json`.
- Blocked book-level: ví dụ `corpus/sources/maslow/CORPUS_BLOCKED.md` (*Motivation and Personality* ©).

**Lệch catalog:** ~26 license id đang dùng **không** có trong `licenses.json` (`public_domain_usa_archive_1899`, `public_domain_vn_curator_khung`, `public_domain_primary_excerpt`, …). Catalog có `cc0`/`cc_by`/`vn_nom_pd` nhưng **chưa dùng** trên works.

**Không có** `rights.consumers.think|read` hay `distribution: preview_only`.

---

## 3. Inventory corpus

Snapshot disk local (kể cả `raw/` không commit):

| Metric | Số |
|--------|-----|
| Brains (registry = profiles = forests) | **286** |
| `ready: true` | 137 |
| Forest `approved` / `draft` | 148 / 138 |
| `works.json` rows (tác phẩm-file) | **568** |
| Mọi `file` kết thúc `.txt` | 568 |
| `chunks.jsonl` + `manifest.json` | 286 brains (mọi brain registry) |
| Tổng `chunk_count` (manifest) | **287 404** |
| Raw dirs / raw files / `.txt` raw | 242 / 502 / 498 |
| Declared `file` có raw trên máy này | 469 |
| Declared `file` **thiếu raw** | **99** |
| Sources orphan | `wordsworth/` (chỉ `raw/`, không trong registry) |
| `corpusKind` trên profile | 149 thiếu; 77 `primary`; wedge còn lại |
| Spaces | 27 |
| Corpus size (cả chunks) | ~861 MB |

**License mix (568 works):**

- 362 `public_domain_usa_gutenberg`
- 93 `public_domain_vn_wikisource`
- 44 `public_domain_usa_archive`
- 12 `public_domain_jp_aozora`
- còn lại: Archive theo năm, journal, excerpt, khung curator VN, 1 `vn_translation_pd`, 1 `public_domain_vn_nguyen_tao_1972`

**Ngôn ngữ works.json:** 439 không ghi `lang` (xem là EN), 104 `vi`, 12 `ja`, 12 `fr`, 1 `en` tường minh.

**Naming:**

- Brain id: slug `[a-z][a-z0-9_]{1,40}` (CMS).
- File: slug `.txt` (`my_life_vol1.txt`, `tu_thuat.txt`).
- Work **title không unique:** cùng title nhiều file (thơ VN cắt lát), và *The Art of War* trùng giữa `sunzi` / `machiavelli` / `jomini`. Identity hiện tại = `(brain_id, file)` hoặc `(brain_id, work title)` — **gãy** khi title trùng trong cùng brain.

**Hai tầng nội dung (không phải “một `.txt` = product Work” theo nghĩa Hub/Read):**

1. `raw/*.txt` — Gutenberg/Archive/Wikisource/Aozora, local-only.
2. `chunks/` — cửa sổ ~1400 ký tự, overlap ~160 (`ingest_pd.py`); Think **không** giữ full text trên server production (sync bỏ `raw/`).

Forest `corpus/forests/<id>.md` (~400–800 chữ VN) là compass — nội dung curator, không phải PD book.

---

## 4. Chỗ Think đọc corpus trực tiếp

Luồng sản phẩm: **không có đọc `.txt` trên request path.**

```
raw/*.txt  --ingest_pd.py-->  chunks.jsonl
                                  │
                    retrieve.py / content_retrieve.py / work_samples.py
                                  │
                         pipeline.py (salon LLM)
                                  │
                    mobile  ←──  API + @think/shared catalog
```

| Ai | Đọc gì | Path |
|----|--------|------|
| `retrieve.py` | `chunks.jsonl` + `works.json` (lang) + `skip.json` | RAG TF index per brain |
| `content_retrieve.py` | cùng retrieve | Stage 2 sau director |
| `work_samples.py` | `load_chunks` | `GET /brains/{id}/works/samples` — vài đoạn, **không full book** |
| `forest.py` | `corpus/forests/<id>.md` | Prompt compass |
| `catalog.py` | registry, profiles, works.json, manifests | Shelf / completeness / generate shared |
| `match_vec.py` | chunks + works.json + forest | Cast vectors |
| `pipeline.py` | `retrieve` + `load_forest` | Mỗi lượt salon |
| `admin.py` | raw tồn tại?, ingest subprocess, list/skip chunks | Curator only |
| `ingest_pd.py` / `fetch_raw_pd.py` | `raw/<file>.txt` | Offline / nút CMS |
| Mobile | `@think/shared` (brains, cards, corpusKind) | **Không** mở corpus files |
| Mobile `work-samples.tsx` | HTTP samples API | Preview, không TTS fulltext |
| CMS UI | chỉ `/admin` | Không đọc disk từ browser |

`has_corpus(brain)` = **tồn tại `chunks.jsonl`**, không phải có raw.

Production: `THINK_CORPUS_ROOT` có thể trỏ GCS mount; curator sync `scripts/sync-corpus-gcs-fast.sh` (forests, profiles, registry, chunks — **không raw**).

---

## 5. Gap vs Knowledge Hub (Phase 1+)

Ánh xạ đề xuất (chưa implement):

| Hub concept | Think hôm nay | Việc Phase 1 |
|-------------|----------------|--------------|
| `Work.id` ổn định | `(brain, file)` ngầm | Thêm UUID/slug **không đổi**; title chỉ display |
| `author_id` | `brain.id` (và wedge = người khác viết) | Tách Author vs Brain vs Work; wedge cần `author_id` ≠ brain |
| `content_hash` SHA-256 `.txt` | Chỉ SHA-1 10 ký tự / chunk | Hash raw khi ingest; lưu trên works.json |
| `version` + `publications` | Không | Bảng/JSON publications + bump khi hash đổi |
| `status` draft/review/published | Brain `ready` + forestStatus; work không có | Status per work + per consumer |
| Consumer rights | Không | `rights.consumers.read` |
| Hub API list/get/content | Admin chunks + public samples | Read API mới; **content** = raw hoặc reconstruct? Raw không có trên Cloud Run |
| Read sync-copy full text | Think **cố ý không** giữ fulltext runtime | Phải quyết định: giữ raw trên Hub storage, hoặc export từ chunks (mất cấu trúc sách) |

**Rủi ro lớn nhất cho Read:** full manuscript nằm ở KnowledgeHub `raw/` (local/gitignored). Cloud Run Think **không** có raw. Sync Read cần đọc Hub disk/bucket, không reconstruct từ chunks.

**Rủi ro identity:** title `work` dùng làm join (`corpusWorks` trên profile, query `corpusWork=`). Trùng title → samples/ingest sai não.

**Rủi ro license:** allowlist prefix quá rộng vs catalog hẹp → Hub schema nên chuẩn hoá enum + map id cũ.

---

## 6. Việc Think app đọc trực tiếp — checklist thay Hub API

Ưu tiên thay (Phase 2), không phải hết trong Phase 1:

1. `retrieve.brain_corpus` / `chunks_path` — hot path salon  
2. `load_forest` — mỗi reply  
3. `GET /brains/{id}/works/samples` — profile reader  
4. `generate_shared_catalog.py` + mobile `@think/shared` — metadata kệ  
5. `catalog.has_corpus` / casting pool — “có thể cast”

Phase 1 có thể **bọc** các hàm trên bằng Hub client nội bộ (`USE_HUB_API`) mà chưa đổi mobile, miễn API public samples + salon vẫn cùng contract.

---

## 7. Gợi ý Phase 1 (sau audit)

Trong Think CMS / API, tối thiểu:

1. **Work identity:** `id` (slug) trên mỗi row `works.json`; cấm trùng trong một brain.  
2. **`content_hash`** + `ingested_at` khi chạy `ingest_pd.py`.  
3. **Chuẩn hoá license id** (map 26 id lẻ → catalog; cấm id mới ngoài catalog).  
4. **Quyết định storage canonical text** cho consumer Read (raw bucket vs cấm fulltext).  
5. **Publications stub:** `consumers: [think]` mặc định; chưa expose Read.  
6. Giữ CMS UI hiện tại; thêm tab Publications sau khi (1)–(3) ổn.

Không tách repo implementation cho đến khi `GET /hub/works/{id}` + content ổn định (đúng PROJECT.md §8).

---

## 8. Câu hỏi mở còn lại (sau audit)

| # | Câu hỏi | Ghi chú từ Phase 0 |
|---|---------|---------------------|
| 1 | Read auto-publish vs `pending_review`? | Chưa có signal trong Think |
| 2 | Pricing mặc định trên Read? | Không có field giá trên works |
| 3 | Think export **raw** hay **chunks** cho embedding? | Think **đã index chunks**; embedding/RAG không cần raw. Read/Hub canonical **cần raw** (hoặc bản strip) |
| 4 | Filesystem vs DB? | **Đã chốt:** filesystem Git + GCS; SQLite không phải corpus |
| 5 | **Mới:** Hub `Work` = một `works.json` row (một `.txt`) hay một title gộp nhiều file thơ? | Data hiện tại: một row = một file; UI profile gộp `corpusWorks` |
| 6 | **Mới:** Brain wedge — `author` của text ≠ human được “call”? | Cần model rights + attribution khác `brainId` |

---

*Phase 0 xong. Implementation Hub API = Phase 1 trên repo Think, không trên KnowledgeHub docs-only.*
