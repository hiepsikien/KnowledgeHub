# Tài liệu dự án Knowledge Hub

> **Knowledge Hub** là lớp quản lý và phân phối corpus văn học tập trung — nguồn sự thật duy nhất cho tác phẩm, tác giả, license và trạng thái xuất bản. **Think** và **Read** là hai ứng dụng tiêu thụ (consumer), không sở hữu corpus gốc.

- **Repo (dự kiến):** https://github.com/hiepsikien/KnowledgeHub  
- **Triển khai:** catalog + CLI trên repo này; Think chỉ còn consumer RAG; Read nhận sync-copy  
- **Consumer:** [Think](https://github.com/hiepsikien/Think) · [Read](https://github.com/hiepsikien/Read)  
- **Trạng thái:** Catalog Hub v1 + curator UI (`knowledgehub serve`) + `publish-read`; Think CMS không còn là nơi quản lý tài liệu Hub 

---

## 1. Bối cảnh

### Corpus hiện tại (Think)

| Đặc điểm | Mô tả |
|----------|--------|
| Định dạng | **Plain text (`.txt`)** |
| Glossary nhân vật | **Không có** |
| Series / season / episode | **Không có** — mỗi file là một tác phẩm độc lập |
| Metadata | Có **author** và metadata khác nhưng **chưa thống nhất** — cần chuẩn hoá |
| License | Đã quản lý trong **CMS Think** (trong `apps/`) |
| Quản trị | CMS Think đang là nơi quản lý corpus + license |

### Vấn đề cần giải quyết

1. **Hai app cần cùng một corpus** nhưng dùng theo cách khác nhau (Think: học / AI / corpus; Read: đọc in-app, TTS, thư viện).
2. **Metadata lộn xộn** — khó sync tự động nếu không có schema chung.
3. **Xây CMS mới từ đầu** sẽ trùng lặp công việc license + corpus đã có trong Think.
4. **Read** cần bản sao tối ưu cho đọc (split chapter, TTS); **Think** cần full text + metadata cho AI/RAG.

### Quyết định kiến trúc

> **KnowledgeHub quản lý tài liệu.** Think không còn là CMS corpus.  
> Think ingest `.txt` từ `corpus/sources/` nếu cần RAG. Read nhận bản copy qua `knowledgehub publish-read`.

Product name: **Knowledge Hub**.  
Implementation: Python package `knowledgehub` trong repo này (`src/knowledgehub`).

---

## 2. Mục tiêu sản phẩm

Knowledge Hub cho phép:

1. **Quản lý corpus** — ingest, chuẩn hoá, version `.txt`
2. **Quản lý tác giả** — entity riêng, không còn string rời rạc
3. **Quản lý license & quyền phân phối** — theo consumer (Think / Read)
4. **Publish có kiểm soát** — snapshot versioned cho từng app
5. **Làm publisher trung tâm** — cung cấp nội dung cho Think và Read

---

## 3. Kiến trúc tổng thể

```
┌─────────────────────────────────────────────────────────┐
│  KnowledgeHub                                           │
│  catalog/works.json · authors.json · licenses           │
│  sources/<brain>/raw/*.txt (canonical manuscripts)      │
│  CLI + UI: serve · allow-read · publish-read            │
└──────────────────────────┬──────────────────────────────┘
           ┌───────────────┴───────────────┐
           ▼                               ▼
    Think (optional ingest)         Read POST /api/internal/hub/works
    chunks / salon                  books.hub_work_id + split chapters
```

### Vai trò từng thành phần

| Thành phần | Vai trò |
|------------|---------|
| **Knowledge Hub** | Source of truth — catalog Work/Author/license + raw `.txt` + publish CLI |
| **Think app** | Consumer RAG — có thể đọc `sources/` để chunk; không sở hữu catalog |
| **Read** | Consumer đọc sách — `POST /api/internal/hub/works` → `raw_text` + chapters |
| **Repo KnowledgeHub** | Docs, schema, catalog, CLI `knowledgehub` |
| **Repo Think** | Salon, forests, chunks derived |
| **Repo Read** | Reader + TTS + cửa ingest Hub (`HUB_SYNC_TOKEN`) |

---

## 4. Mô hình dữ liệu

### 4.1. Work (tác phẩm)

Một Work = **một file `.txt`** + metadata chuẩn hoá.

| Field | Bắt buộc | Ghi chú |
|-------|----------|---------|
| `id` | ✓ | Slug/UUID **ổn định**, không đổi |
| `title` | ✓ | Tiêu đề hiển thị |
| `author_id` | ✓ | FK → `authors` |
| `language` | ✓ | BCP-47: `vi`, `en`, … |
| `description` | Khuyến nghị | Mô tả / blurb |
| `tags` / `genre` | Tuỳ chọn | Tiểu thuyết, luận văn, lịch sử, … |
| `content_hash` | ✓ | SHA-256 của nội dung `.txt` |
| `status` | ✓ | `draft` · `review` · `published` · `archived` |
| `version` | ✓ | Tăng mỗi khi nội dung đổi |

**Không có ở v1:** series, season, episode, glossary nhân vật.

### 4.2. Author (tác giả)

```yaml
id: tac-gia-slug
name: "Tên hiển thị"
name_sort: "Ten hien thi"    # tìm kiếm / sắp xếp
aliases: ["Bút danh A"]
bio: ""
```

### 4.3. License & quyền (Rights)

Kế thừa model license CMS Think, mở rộng cho multi-consumer:

```yaml
rights:
  basis: public_domain | licensed | original | editorial_derivative
  attribution_required: true
  attribution_text: "Trích dẫn bắt buộc nếu có"
  consumers:
    think: allowed
    read:
      distribution: allowed | preview_only | blocked
      pricing_default: free    # gợi ý; Read có thể có policy riêng
```

#### Ghi chú: Tác phẩm public domain (PD) và thu phí trên Read

*Đây là định hướng sản phẩm / pháp lý, không phải tư vấn luật.*

| Được phép | Không được |
|-----------|------------|
| Thu phí **dịch vụ nền tảng** (đọc in-app, TTS, UX) | Coi PD text là **tài sản độc quyền** |
| Thu phí **bản biên tập** nếu có lớp biên tập đáng kể (chú thích, hiện đại hoá ngôn ngữ, dịch mới, bố cục lại) | Chặn người khác xuất bản cùng bản PD gốc |
| Ghi rõ trên Read: bản PD + edition/biên tập của Hub | Bán mà không ghi license / attribution |

**Mức biên tập:**

| Mức | Ý nghĩa |
|-----|---------|
| Nhẹ (sửa encoding, xuống dòng) | Thu phí chủ yếu là **platform fee** |
| Đáng kể (notes, intro, ngôn ngữ hiện đại, dịch mới) | Có thể coi là **edition** — bảo vệ lớp biên tập |

### 4.4. Publication (xuất bản cho consumer)

```yaml
work_id: vi-du-work
version: 3
consumers: [think, read]
published_at: "2026-08-26T12:00:00Z"
published_by: admin-user-id
```

Một Work có thể:

- Chỉ publish cho **Think**
- Publish cho **cả Think và Read**
- **Archive** — consumers nhận tín hiệu gỡ / ẩn

---

## 5. Think ↔ Hub

### CMS Think (`apps/`)

**Giữ nguyên:** quản lý corpus, author, license, admin UI.  
**Bổ sung:**

- Model `content_version`, `content_hash`
- Bảng `publications` / consumer flags
- Hub read API
- UI rebrand → **Knowledge Hub** (product name)

### Think app

| Trước | Sau |
|-------|-----|
| Đọc file `.txt` / DB trực tiếp | `hubClient.getWork(id)`, `getContent()` |
| License rải rác | Nhận từ metadata Hub |

Migration có feature flag `USE_HUB_API=true`.

---

## 6. Read ↔ Hub

### Mô hình: sync-copy (materialized)

Read **lưu full text local** sau khi sync — **không** gọi Hub API mỗi lần user mở chapter.

**Lý do:**

- Reader + TTS + explain cần latency thấp
- Mobile / offline
- Read đã có pipeline smart-split → `chapters.content`
- Hub downtime không làm sách đã sync không đọc được

### Luồng sync

```
Hub publish work (txt + metadata + license)
    ↓
Read sync job (sync_from_hub)
    ↓ validate license.read.distribution
    ↓ upsert book (hub_work_id, hub_version, hub_content_hash)
    ↓ copy raw_text
    ↓ smart split → chapters
    ↓ (tuỳ policy) draft | pending_review | published
```

### Dữ liệu Read lưu thêm

| Field | Mục đích |
|-------|----------|
| `hub_work_id` | Liên kết Work Hub |
| `hub_version` | Detect bản mới |
| `hub_content_hash` | Idempotent sync |
| `hub_synced_at` | Audit |
| `hub_license_snapshot` | JSON license tại thời điểm sync |

### Read **không** lưu / **không** cần realtime

- Draft chưa publish trên Hub
- Lịch sử version đầy đủ (trừ snapshot audit)
- Fulltext proxy mỗi lần đọc

### Khi Read gọi Hub API

| Tình huống | Gọi Hub? |
|------------|----------|
| User đang đọc chapter | Không |
| TTS / explain | Không |
| Sync định kỳ / webhook `work.published` | Có |
| Admin “Refresh from Hub” | Có |
| Bản mới available (so version) | Có (metadata) |

---

## 7. Hub API (mục tiêu)

| Method | Path | Mô tả |
|--------|------|--------|
| GET | `/hub/works?status=published&consumer=think` | Danh sách Work |
| GET | `/hub/works/{id}` | Metadata + license |
| GET | `/hub/works/{id}/content` | Nội dung `.txt` |
| GET | `/hub/authors/{id}` | Tác giả |
| GET | `/hub/exports/read/delta?since={cursor}` | Sync incremental cho Read |
| POST | `/hub/internal/works/{id}/publish` | Admin publish |

**Auth:** service token cho Read sync / CI; session admin cho CMS UI.

---

## 8. Phân tách repo

| Repo | Nội dung |
|------|----------|
| **KnowledgeHub** | Catalog, curator UI, licenses, CLI validate/hash/publish-read |
| **Think** | Forests + RAG chunks (derived) |
| **Read** | `hub_work_id` trên `books`, `POST /api/internal/hub/works` |

Think **không** quản lý catalog Hub. `sources/*/works.json` còn lại là bản Think-shaped để ingest RAG; nguồn sự thật quản trị là `corpus/catalog/`.

---

## 9. Roadmap

### Phase 0 — Audit Think

- [x] Map `apps/cms` — stack, models, license fields
- [x] Inventory corpus `.txt` — naming, metadata hiện có
- [x] Tìm chỗ Think app đọc corpus trực tiếp
- [x] Output: [`docs/hub-evolution.md`](./hub-evolution.md) (2026-08-27, local Think clone)

### Phase 1 — Catalog + publish Read

- [x] Work `id` ổn định (`{brain}--{file_stem}`) + `author_id`
- [x] `content_hash` SHA-256 (`knowledgehub hash`)
- [x] Chuẩn hóa license (canonical + aliases)
- [x] Module `knowledgehub publish-read` → Read `pending_review`
- [x] Curator UI (`knowledgehub serve`) — list, allow-read, dry-run / apply
- [x] Normalize lúc `publish-read` (cắt Gutenberg / note eBook / TOC; unwrap hard-wrap; không ghi đè `raw/`)
- [ ] Consumer flags hàng loạt / bulk allow-read

### Phase 2 — Think app refactor

- [ ] Pilot 1 flow qua Hub API
- [ ] Feature flag rollout

### Phase 3 — Read integration

- [ ] Migration `hub_work_id` trên `books`
- [ ] `sync_from_hub` job
- [ ] Plain-text ingest path (không bắt DOCX cho kênh Hub)
- [ ] Pilot 3–5 works lên Library

### Phase 4 — Chuẩn hoá metadata

- [ ] Author deduplication
- [ ] Review queue
- [ ] Bulk publish

---

## 10. Quyết định đã chốt

| Hạng mục | Quyết định |
|----------|------------|
| Source of truth | KnowledgeHub `corpus/catalog` + `sources/*/raw` |
| Định dạng corpus | `.txt` |
| Series / glossary | Không ở v1 |
| Read lưu fulltext? | **Có** — sync-copy qua Hub ingest |
| Think đọc fulltext? | Optional ingest từ `sources/`; salon dùng chunks |
| Publisher logic | Hub `allow-read` rồi `publish-read --apply` |
| Catalog Work id | `{think_brain}--{file_stem}` |

## 11. Quyết định còn mở

| # | Câu hỏi |
|---|---------|
| 1 | Read auto-publish sau Hub publish, hay `pending_review`? |
| 2 | Pricing mặc định work Hub trên Read? |
| 3 | Think cần export **raw** hay **chunks** cho embedding? |
| 4 | Corpus `.txt` lưu filesystem hay DB? | **Chốt:** canonical filesystem dưới **KnowledgeHub/corpus**. Think chỉ giữ chunks derived + mirror `works.json` cho GCS. SQLite không chứa corpus. |

---

## 12. Liên kết

- Read: https://github.com/hiepsikien/Read — [docs/PROJECT.md](https://github.com/hiepsikien/Read/blob/main/docs/PROJECT.md)
- Think: https://github.com/hiepsikien/Think (private) — CMS trong `apps/`

---

*Tài liệu này là bản mô tả sản phẩm Knowledge Hub — cập nhật khi audit Think hoàn tất.*
